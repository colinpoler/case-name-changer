# Mostly copied from https://github.com/JoshData/pdf-redactor

import sys
from datetime import datetime
import subprocess

from pdfrw import PdfDict, PdfReader, PdfWriter

def read_document(filename):
    return PdfReader(filename)

def unlock_pdf(input_filename, output_filename):
    pdftk = subprocess.Popen(['pdftk', input_filename, 'output', output_filename, 'uncompress'], stdout=subprocess.PIPE)
    pdftk.wait()

def write_document(document, filename):
    writer = PdfWriter()
    writer.trailer = document
    writer.write(filename)

class InlineImage(PdfDict):
    def read_data(self, tokens):
        # "Unless the image uses ASCIIHexDecode or ASCII85Decode as one
        # of its filters, the ID operator should be followed by a
        # single white-space character, and the next character is
        # interpreted as the first byte of image data.
        if tokens.current[0][1] > tokens.current[0][0] + 3:
            tokens.current[0] = (tokens.current[0][0],
                    tokens.current[0][0] + 3)

        start = tokens.floc
        state = 0
        whitespace = (" ", "\n", "\r")
        # 0: image data or trailing whitespace
        # 1: E
        # 2: I
        for i in range(start, len(tokens.fdata)):
            if state == 0:
                if tokens.fdata[i] == "E":
                    state = 1
            elif state == 1:
                if tokens.fdata[i] == "I":
                    state = 2
                else:
                    state = 0
            elif state == 2:
                if tokens.fdata[i] in whitespace:
                    for j in range(i + 1, i + 6):
                        o = ord(tokens.fdata[j])
                        if o == 0x0A:  # \n
                            continue
                        elif o == 0x0D:  # \r
                            continue
                        elif o >= 0x20 and o <= 0x7E:
                            continue
                        else:
                            state = 0
                            break
                    else:
                        end = i - 3
                        assert tokens.fdata[end] in whitespace
                        break
                else:
                    state = 0

        self._stream = tokens.fdata[start:end]
        tokens.floc = end


def tokenize_streams(streams):
    # pdfrw's tokenizer PdfTokens does lexical analysis only. But we need
    # to collapse arrays ([ .. ]) and dictionaries (<< ... >>) into single
    # token entries.
    from pdfrw import PdfTokens, PdfArray
    stack = []
    for stream in streams:
        tokens = PdfTokens(stream)
        for token in tokens:
            # Is this a control token?
            if token == "<<":
                # begins a dictionary
                stack.append((PdfDict, []))
                continue
            elif token == "[":
                # begins an array
                stack.append((PdfArray, []))
                continue
            elif token in (">>", "]"):
                # ends a dictionary or array
                constructor, content = stack.pop(-1)
                if constructor == PdfDict:
                    # Turn flat list into key/value pairs.
                    content = chunk_pairs(content)
                token = constructor(content)
            elif token == "BI":
                # begins an inline image's dictionary half
                stack.append((InlineImage, []))
                continue
            elif token == "ID":
                # divides an inline image's dictionary half and data half
                constructor, content = stack[-1]
                content = chunk_pairs(content)
                img = constructor(content)
                img.read_data(tokens)
                stack[-1] = (img, None)
                continue
            elif token == "EI":
                # ends an inline image
                token, _ = stack.pop(-1)

            # If we're inside something, add this token to that thing.
            if len(stack) > 0:
                stack[-1][1].append(token)
                continue

            # Yield it.
            yield token


def build_text_layer(document):
    # Within each page's content stream, look for text-showing operators to
    # find the text content of the page. Construct a string that contains the
    # entire text content of the document AND a mapping from characters in the
    # text content to tokens in the content streams. That lets us modify the
    # tokens in the content streams when we find text that we want to redact.
    #
    # The text-showing operators are:
    #
    #   (text) Tj      -- show a string of text
    #   (text) '       -- move to next line and show a string of text
    #   aw ac (text) " -- show a string of text with word/character spacing parameters
    #   [ ... ] TJ     -- show text strings from the array, which are interleaved with spacing parameters
    #
    # (These operators appear only within BT ... ET so-called "text objects",
    # although we don't make use of it.)
    #
    # But since we don't understand any of the other content stream operators,
    # and in particular we don't know how many operands each (non-text) operator
    # takes, we can never be sure whether what we see in the content stream is
    # an operator or an operand. If we see a "Tj", maybe it is the operand of
    # some other operator?
    #
    # We'll assume we can get by just fine, however, assuming that whenever we
    # see one of these tokens that it's an operator and not an operand.
    #
    # But TJ remains a little tricky because its operand is an array that preceeds
    # it. Arrays are delimited by square brackets and we need to parse that.
    #
    # We also have to be concerned with the encoding of the text content, which
    # depends on the active font. With a simple font, the text is a string whose
    # bytes are glyph codes. With a composite font, a CMap maps multi-byte
    # character codes to glyphs. In either case, we must map glyphs to unicode
    # characters so that we can pattern match against it.
    #
    # To know the active font, we look for the "<font> <size> Tf" operator.

    from pdfrw import PdfObject, PdfString, PdfArray
    from pdfrw.uncompress import uncompress as uncompress_streams
    from pdfrw.objects.pdfname import BasePdfName

    text_tokens = []
    fontcache = { }

    class TextToken:
        value = None
        font = None
        def __init__(self, value, font):
            self.font = font
            self.raw_original_value = value
            self.original_value = toUnicode(value, font, fontcache)
            self.value = self.original_value
        def __str__(self):
            # __str__ is used for serialization
            if self.value == self.original_value:
                # If unchanged, return the raw original value without decoding/encoding.
                return PdfString.from_bytes(self.raw_original_value)
            else:
                # If the value changed, encode it from Unicode according to the encoding
                # of the font that is active at the location of this token.
                return PdfString.from_bytes(fromUnicode(self.value, self.font, fontcache))
        def __repr__(self):
            # __repr__ is used for debugging
            return "Token<%s>" % repr(self.value)

    def process_text(token):
        if token.value == "": return
        text_tokens.append(token)

    # For each page...
    page_tokens = []
    for page in document.pages:
        # For each token in the content stream...

        # Remember this page's revised token list.
        token_list = []
        page_tokens.append(token_list)

        if page.Contents is None:
            continue

        prev_token = None
        prev_prev_token = None
        current_font = None

        # The page may have one content stream or an array of content streams.
        # If an array, they are treated as if they are concatenated into a single
        # stream (per the spec).
        if isinstance(page.Contents, PdfArray):
            contents = list(page.Contents)
        else:
            contents = [page.Contents]

        # If a compression Filter is applied, attempt to un-apply it. If an unrecognized
        # filter is present, an error is raised. uncompress_streams expects an array of
        # streams.
        uncompress_streams(contents)

        def make_mutable_string_token(token):
            if isinstance(token, PdfString):
                token = TextToken(token.to_bytes(), current_font)

                # Remember all unicode characters seen in this font so we can
                # avoid inserting characters that the PDF isn't likely to have
                # a glyph for.
                if current_font and current_font.BaseFont:
                    fontcache.setdefault(current_font.BaseFont, set()).update(token.value)
            return token

        # Iterate through the tokens in the page's content streams.
        for token in tokenize_streams(content.stream for content in contents):
            # Replace any string token with our own class that hold a mutable
            # value, which is how we'll rewrite content.
            token = make_mutable_string_token(token)

            # Append the token into a new list that holds all tokens.
            token_list.append(token)

            # If the token is an operator and we're not inside an array...
            if isinstance(token, PdfObject):
                # And it's one that we recognize, process it.
                if token in ("Tj", "'", '"') and isinstance(prev_token, TextToken):
                    # Simple text operators.
                    process_text(prev_token)
                elif token == "TJ" and isinstance(prev_token, PdfArray):
                    # The text array operator.
                    for i in range(len(prev_token)):
                        # (item may not be a string! only the strings are text.)
                        prev_token[i] = make_mutable_string_token(prev_token[i])
                        if isinstance(prev_token[i], TextToken):
                            process_text(prev_token[i])

                elif token == "Tf" and isinstance(prev_prev_token, BasePdfName):
                    # Update the current font.
                    # prev_prev_token holds the font 'name'. The name must be looked up
                    # in the content stream's resource dictionary, which is page.Resources,
                    # plus any resource dictionaries above it in the document hierarchy.
                    current_font = None
                    resources = page.Resources
                    while resources and not current_font:
                        current_font = resources.Font[prev_prev_token]
                        resources = resources.Parent

            # Remember the previously seen token in case the next operator is a text-showing
            # operator -- in which case this was the operand. Remember the token before that
            # because it may be a font name for the Tf operator.
            prev_prev_token = prev_token
            prev_token = token

    return (text_tokens, page_tokens)


def chunk_pairs(s):
    while len(s) >= 2:
        yield (s.pop(0), s.pop(0))


def chunk_triples(s):
    while len(s) >= 3:
        yield (s.pop(0), s.pop(0), s.pop(0))


class CMap(object):
    def __init__(self, cmap):
        self.bytes_to_unicode = { }
        self.unicode_to_bytes = { }
        self.defns = { }
        self.usecmap = None

        # Decompress the CMap stream & check that it's not compressed in a way
        # we can't understand.
        from pdfrw.uncompress import uncompress as uncompress_streams
        uncompress_streams([cmap])

        #print(cmap.stream, file=sys.stderr)

        # This is based on https://github.com/euske/pdfminer/blob/master/pdfminer/cmapdb.py.
        from pdfrw import PdfString, PdfArray
        in_cmap = False
        operand_stack = []
        codespacerange = []

        def code_to_int(code):
            # decode hex encoding
            code = code.to_bytes()
            if sys.version_info < (3,):
                code = (ord(c) for c in code)
            from functools import reduce
            return reduce(lambda x0, x : x0*256 + x, (b for b in code))

        def add_mapping(code, char, offset=0):
            # Is this a mapping for a one-byte or two-byte character code?
            width = len(codespacerange[0].to_bytes())
            assert len(codespacerange[1].to_bytes()) == width
            if width == 1:
                # one-byte entry
                if sys.version_info < (3,):
                    code = chr(code)
                else:
                    code = bytes([code])
            elif width == 2:
                if sys.version_info < (3,):
                    code = chr(code//256) + chr(code & 255)
                else:
                    code = bytes([code//256, code & 255])
            else:
                raise ValueError("Invalid code space range %s?" % repr(codespacerange))

            # Some range operands take an array.
            if isinstance(char, PdfArray):
                char = char[offset]

            # The Unicode character is given usually as a hex string of one or more
            # two-byte Unicode code points.
            if isinstance(char, PdfString):
                char = char.to_bytes()
                if sys.version_info < (3,): char = (ord(c) for c in char)

                c = ""
                for xh, xl in chunk_pairs(list(char)):
                    c += (chr if sys.version_info >= (3,) else unichr)(xh*256 + xl)
                char = c

                if offset > 0:
                    char = char[0:-1] + (chr if sys.version_info >= (3,) else unichr)(ord(char[-1]) + offset)
            else:
                assert offset == 0

            self.bytes_to_unicode[code] = char
            self.unicode_to_bytes[char] = code

        for token in tokenize_streams([cmap.stream]):
            if token == "begincmap":
                in_cmap = True
                operand_stack[:] = []
                continue
            elif token == "endcmap":
                in_cmap = False
                continue
            if not in_cmap:
                continue
            
            if token == "def":
                name = operand_stack.pop(0)
                value = operand_stack.pop(0)
                self.defns[name] = value

            elif token == "usecmap":
                self.usecmap = self.pop(0)

            elif token == "begincodespacerange":
                operand_stack[:] = []
            elif token == "endcodespacerange":
                codespacerange = [operand_stack.pop(0), operand_stack.pop(0)]

            elif token in ("begincidrange", "beginbfrange"):
                operand_stack[:] = []
            elif token in ("endcidrange", "endbfrange"):
                for (code1, code2, cid_or_name1) in chunk_triples(operand_stack):
                    if not isinstance(code1, PdfString) or not isinstance(code2, PdfString): continue
                    code1 = code_to_int(code1)
                    code2 = code_to_int(code2)
                    for code in range(code1, code2+1):
                        add_mapping(code, cid_or_name1, code-code1)
                operand_stack[:] = []

            elif token in ("begincidchar", "beginbfchar"):
                operand_stack[:] = []
            elif token in ("endcidchar", "endbfchar"):
                for (code, char) in chunk_pairs(operand_stack):
                    if not isinstance(code, PdfString): continue
                    add_mapping(code_to_int(code), char)
                operand_stack[:] = []

            elif token == "beginnotdefrange":
                operand_stack[:] = []
            elif token == "endnotdefrange":
                operand_stack[:] = []

            else:
                operand_stack.append(token)

    def dump(self):
        for code, char in self.bytes_to_unicode.items():
            print(repr(code), char)

    def decode(self, string):
        ret = []
        i = 0;
        while i < len(string):
            if string[i:i+1] in self.bytes_to_unicode:
                # byte matches a single-byte entry
                ret.append( self.bytes_to_unicode[string[i:i+1]] )
                i += 1
            elif string[i:i+2] in self.bytes_to_unicode:
                # next two bytes matches a multi-byte entry
                ret.append( self.bytes_to_unicode[string[i:i+2]] )
                i += 2
            else:
                ret.append("?")
                i += 1
        return "".join(ret)

    def encode(self, string):
        ret = []
        for c in string:
            ret.append(self.unicode_to_bytes.get(c, b""))
        return b"".join(ret)


def toUnicode(string, font, fontcache):
    # This is hard!

    if not font:
        # There is no font for this text. Assume Latin-1.
        return string.decode("Latin-1")
    elif font.ToUnicode:
        # Decompress the CMap stream & check that it's not compressed in a way
        # we can't understand.
        from pdfrw.uncompress import uncompress as uncompress_streams
        uncompress_streams([font.ToUnicode])

        # Use the CMap, which maps character codes to Unicode code points.
        if font.ToUnicode.stream not in fontcache:
            fontcache[font.ToUnicode.stream] = CMap(font.ToUnicode)
        cmap = fontcache[font.ToUnicode.stream]

        string = cmap.decode(string)
        #print(string, end='', file=sys.stderr)
        #sys.stderr.write(string)
        return string
    elif font.Encoding == "/WinAnsiEncoding":
        return string.decode("cp1252", "replace")
    elif font.Encoding == "/MacRomanEncoding":
        return string.decode("mac_roman", "replace")
    else:
        return "?"
        #raise ValueError("Don't know how to decode data from font %s." % font)

def fromUnicode(string, font, fontcache):
    # Encode the Unicode string in the same encoding that it was originally
    # stored in --- based on the font that was active when the token was
    # used in a text-showing operation.
    if not font:
        # There was no font for this text. Assume Latin-1.
        return string.encode("Latin-1")

    elif font.ToUnicode and font.ToUnicode.stream in fontcache:
        # Convert the Unicode code points back to one/two-byte CIDs.
        cmap = fontcache[font.ToUnicode.stream]
        return cmap.encode(string)

    # Convert using a simple encoding.
    elif font.Encoding == "/WinAnsiEncoding":
        return string.encode("cp1252")
    elif font.Encoding == "/MacRomanEncoding":
        return string.encode("mac_roman")

    # Don't know how to handle this sort of font.
    else:
        raise ValueError("Don't know how to encode data to font %s." % font)

def update_text_layer(replacements, text_tokens, page_tokens):
    if len(text_tokens) == 0:
        # No text content.
        return

    # Apply each regular expression to the text content...
    for pattern, function in replacements:
        # Finding all matches...
        text_tokens_index = 0
        text_tokens_charpos = 0
        text_tokens_token_xdiff = 0
        text_content = "".join(t.value for t in text_tokens)
        for m in pattern.finditer(text_content):
            # We got a match at text_content[i1:i2].
            i1 = m.start()
            i2 = m.end()

            # Pass the matched text to the replacement function to get replaced text.
            replacement = function(m)

            # Do a text replacement in the tokens that produced this text content.
            # It may have been produced by multiple tokens, so loop until we find them all.
            while i1 < i2:
                # Find the original tokens in the content stream that
                # produced the matched text. Start by advancing over any
                # tokens that are entirely before this span of text.
                while text_tokens_index < len(text_tokens) and \
                      text_tokens_charpos + len(text_tokens[text_tokens_index].value)-text_tokens_token_xdiff <= i1:
                    text_tokens_charpos += len(text_tokens[text_tokens_index].value)-text_tokens_token_xdiff
                    text_tokens_index += 1
                    text_tokens_token_xdiff = 0
                if text_tokens_index == len(text_tokens): break
                assert(text_tokens_charpos <= i1)

                # The token at text_tokens_index, and possibly subsequent ones,
                # are responsible for this text. Replace the matched content
                # here with replacement content.
                tok = text_tokens[text_tokens_index]

                # Where does this match begin within the token's text content?
                mpos = i1 - text_tokens_charpos
                assert mpos >= 0

                # How long is the match within this token?
                mlen = min(i2-i1, len(tok.value)-text_tokens_token_xdiff-mpos)
                assert mlen >= 0

                # How much should we replace here?
                if mlen < (i2-i1):
                    # There will be more replaced later, so take the same number
                    # of characters from the replacement text.
                    r = replacement[:mlen]
                    replacement = replacement[mlen:]
                else:
                    # This is the last token in which we'll replace text, so put
                    # all of the remaining replacement content here.
                    r = replacement
                    replacement = None # sanity

                # Do the replacement.
                tok.value = tok.value[:mpos+text_tokens_token_xdiff] + r + tok.value[mpos+mlen+text_tokens_token_xdiff:]
                text_tokens_token_xdiff += len(r) - mlen

                # Advance for next iteration.
                i1 += mlen

def apply_updated_text(document, text_tokens, page_tokens):
    # Create a new content stream for each page by concatenating the
    # tokens in the page_tokens lists.
    from pdfrw import PdfArray
    for i, page in enumerate(document.pages):
        if page.Contents is None: continue # nothing was here

        # Replace the page's content stream with our updated tokens.
        # The content stream may have been an array of streams before,
        # so replace the whole thing with a single new stream. Unfortunately
        # the str on PdfArray and PdfDict doesn't work right.
        def tok_str(tok):
            if isinstance(tok, PdfArray):
                return "[ " + " ".join(tok_str(x) for x in tok) + "] "
            if isinstance(tok, InlineImage):
                return "BI " + " ".join(tok_str(x) + " " + tok_str(y) for x,y in tok.items()) + " ID " + tok.stream + " EI "
            if isinstance(tok, PdfDict):
                return "<< " + " ".join(tok_str(x) + " " + tok_str(y) for x,y in tok.items()) + ">> "
            return str(tok)
        page.Contents = PdfDict()
        page.Contents.stream = "\n".join(tok_str(tok) for tok in page_tokens[i])
        page.Contents.Length = len(page.Contents.stream) # reset

