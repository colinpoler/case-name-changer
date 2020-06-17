import argparse
import json

import pdfutils
import nameutils

arg_parser = argparse.ArgumentParser(
    description="""
    Replace character names in a PDF
    Will prompt with suggestions for appropriate names based on census data
    Type `n` for any given name to keep the original
    """,
    formatter_class=argparse.RawTextHelpFormatter
)
arg_parser.add_argument('input_pdf', type=str, help='Filename of input pdf')
arg_parser.add_argument('output_pdf', type=str, help='Filename of output pdf')
arg_parser.add_argument('--read_config', type=str, default=None, help='Input from config json (dict old -> new)')
arg_parser.add_argument('--write_config', type=str, default=None, help='Output to config json (dict old -> new)')
arg_parser.add_argument('--race', type=str, default=None, help='Race of suggested names. Default is random.')
args = arg_parser.parse_args()

# Case studies are often password protected; remove the protection
tmp_pdf = '/tmp/' + args.input_pdf
pdfutils.unlock_pdf(args.input_pdf, tmp_pdf)

# Read the document
document = pdfutils.read_document(tmp_pdf)
text_layer = pdfutils.build_text_layer(document)
text = ''.join([t.value for t in text_layer[0]])

if args.read_config:
    # If a config file is passed, just read that instead of suggesting names
    with open(args.read_config, 'r') as f:
        obj = json.load(f)
    confirmed = {nameutils.tuplify(a): nameutils.tuplify(b) for a, b in obj.items()}
else:
    # Find the names
    names = nameutils.find_names(text)

    # Suggest some names
    suggested = nameutils.get_suggestions(names, args.race)

    # Ask the user
    confirmed = {}
    for old, new in suggested.items():
        response = input('{} [{}]: '.format(nameutils.stringify(old), nameutils.stringify(new)))
        if len(response) == 0:
            confirmed[old] = new
        elif ' ' in response:
            confirmed[old] = nameutils.tuplify(response)
        # If not, it's not a valid name and it's probably a `n`, so ignore it
    
    # If a config file is passed, write to that file so it can be used later
    if args.write_config:
        obj = {nameutils.stringify(a): nameutils.stringify(b) for a, b in confirmed.items()}
        with open(args.write_config, 'w') as f:
            json.dump(obj, f)

# Do the replacements
replacements = nameutils.make_replacers(confirmed)
pdfutils.update_text_layer(replacements, *text_layer)
pdfutils.apply_updated_text(document, *text_layer)

# Write the output
pdfutils.write_document(document, args.output_pdf)

