case-name-changer
=================

This is a simple program to change the names in a business-school case study, or really any PDF. It was developed as a drop in the bucket to correct the overwhelming majority of white names in case studies, by simply replacing the names with common names of color.

* * *

This python program is a tool to help you change the names of people referenced in a PDF file, typically a business-school case study.

Specifically, it does the following:
- Read in a pdf with the old names (`input_pdf`)
- If specified, read in substitutions from a json (`--read_config`)
- Else:
    - Find likely names in the text
    - Suggest a new name to the user based on census data
    - Ask the user what they would like to rename that character
- If specified, write out the substitutions to a json (`--write_config`)
- Write out the pdf with the new names (`output_pdf`)

How to use case-name-changer
----------------------------

### Dependendies

You will need to install a pdf toolkit to remove owner protection:

`sudo apt install pdftk`

You will also need a couple of python libraries:

`pip install pdfrw pandas`

### Usage

```console
user@computer:dir$ python3 changer.py --help
usage: changer.py [-h] [--read_config READ_CONFIG]
                  [--write_config WRITE_CONFIG] [--race RACE]
                  input_pdf output_pdf

    Replace character names in a PDF
    Will prompt with suggestions for appropriate names based on census data
    Type `n` for any given name to keep the original
    

positional arguments:
  input_pdf             Filename of input pdf
  output_pdf            Filename of output pdf

optional arguments:
  -h, --help            show this help message and exit
  --read_config READ_CONFIG
                        Input from config json (dict old -> new)
  --write_config WRITE_CONFIG
                        Output to config json (dict old -> new)
  --race RACE           Race of suggested names. Default is random.

user@computer:dir$ python3 changer.py Manzana.pdf Manzana_diverse.pdf --write_config=Manzana.json
Stanford Junior [Parul Swan]: 
Christoph Loch [Surinder Cody]: 
Paul Grant [Juan Ortiz]: 
Bill Pippin [Bina Glisch]: 
Leland Stanford [Ernest Robinson]: 
Tom Jacobs [Ky Manuel]: 
David Paul [Mario Guel]: 
John Lombard [Eden Lam]:

user@computer:dir$
```

Limitations
-----------

Because the text in a PDF is split across many text elements, some of which split words, the tool can't really squeeze in longer names than were initially present. In some cases, e.g. `Ivy` -> `Mim` there aren't more letters but `M` characters are so wide it will still ruin the kerning, so make sure to check for that.

Additionally, sometimes names aren't correctly detected in some PDFs, because pdfrw can insert/remove random whitespace or jumble words. So this might not work on every PDF.

Acknowledgements
----------------

The PDF code is heavily based on Joshua Tauberer's https://github.com/JoshData/pdf-redactor/

First name data is from Tzioumis, Konstantinos (2018) Demographic aspects of first names, Scientific Data, 5:180025 [dx.doi.org/10.1038/sdata.2018.25] , and slightly tweaked (e.g. remove 'San' to avoid replacing 'San Francisco')

Surname data is from https://github.com/fivethirtyeight/data/tree/master/most-common-name , and slightly tweaked

