import re
import pandas as pd
import json
import random
from functools import partial

# Tzioumis, Konstantinos (2018) Demographic aspects of first names, Scientific Data, 5:180025 [dx.doi.org/10.1038/sdata.2018.25].
firstnames=pd.read_csv('firstnames.csv')
# https://github.com/fivethirtyeight/data/tree/master/most-common-name
surnames=pd.read_csv('surnames.csv')

firstnames_set = set(firstnames['name'])
surnames_set = set(surnames['name'])

def is_wordpair_name(wordpair):
    firstname, surname = wordpair
    if surname == 'Booth':
        print(firstname, surname)

    # If it's not title case, it's not a name
    if not (firstname.title() == firstname and surname.title() == surname):
        return False

    # If first and last name not in database, it's not a name
    if not (firstname.title() in firstnames_set and surname.title() in surnames_set):
        return False

    # If the firstname is too rare, it's not a name
    rowfirstname = firstnames.loc[firstnames['name'] == firstname.title()]
    if rowfirstname['count'].values < 10:
        return False

    # If the surname is too rare, it's not a name
    rowsurname = surnames.loc[surnames['name'] == surname.title()]
    if rowsurname['count'].values < 300:
        return False

    # It's probably a name!
    return True

def find_names(text):
    words = text.split()
    wordpairs = [(words[i], words[i+1]) for i in range(len(words) - 1)]

    names = set([wp for wp in wordpairs if is_wordpair_name(wp)])
    return names

race_codes = [
    ('white', [r'white', r'european', r'caucasian'], 65),
    ('black', [r'black', r'african([\s\-]american)?'], 11),
    ('api', [r'asian', r'(pacific )?islander', r'arabic', r'middle eastern'], 5),
    ('aian', [r'native([\s\-]american)?', r'alaska([\s\-]native)'], 1),
    ('hispanic', [r'hispanic', r'latin(o|a|x)'], 15),
    ('2prace', [r'biracial'], 2),
]
def get_race_code(race):
    if race is None:
        return random.choice(race_codes)[0]
    for race_code, patterns, pct in race_codes:
        if any(re.match(p, race) for p in patterns):
            return race_code
    return '2prace'

suggested_names_used = []
def suggest_name(firstnamelen, surnamelen, race_code=None):
    global suggested_names_used
    # Choose valid lengths
    valid_firstnames = firstnames.loc[(firstnames['name'].str.len() <= firstnamelen) & ~surnames['name'].isin(suggested_names_used)].copy()
    valid_surnames = surnames.loc[(surnames['name'].str.len() <= surnamelen) & ~surnames['name'].isin(suggested_names_used)].copy()

    if race_code is not None:
        pct_race = next(pct for code, patterns, pct in race_codes if code == race_code)
        race_code = 'pct' + race_code

        # Make sure it is likely the right race
        valid_firstnames = valid_firstnames.loc[valid_firstnames[race_code] / pct_race > 1]
        valid_surnames = valid_surnames.loc[valid_surnames[race_code] / pct_race > 1]
        
        # Modify the weights based on pct of this race
        valid_firstnames['count'] *= valid_firstnames[race_code]
        valid_surnames['count'] *= valid_surnames[race_code]

    # Choose randomly based on count
    firstname = valid_firstnames.sample(1, weights=valid_firstnames['count'])['name'].iloc[0]
    surname = valid_surnames.sample(1, weights=valid_surnames['count'])['name'].iloc[0]

    suggested_names_used += [firstname, surname]
    return firstname, surname

def get_suggestions(old_names, race=None):
    return {old: suggest_name(len(old[0]), len(old[1]), get_race_code(race)) for old in old_names}

def stringify(t):
    return "{} {}".format(t[0], t[1])
def tuplify(s):
    return tuple(s.split())

def case_insensitive_replacer(old, new):
    return partial(re.sub, old, new, flags=re.IGNORECASE)
def get_group(s):
    return s.group()
def compose(*fs):
    def func(x):
        result = x
        for f in fs:
            result = f(result)
        return result
    return func
def make_replacers(names):
    replacers = []
    for old, new in names.items():
        # First in tuple is regex to match either full name, first name or last name
        regex = re.compile('\s({}\s{}|{}|{})\s'.format(old[0],old[1],old[0],old[1]), flags=re.IGNORECASE)
        # Second in tuple is a function to change either full name, first name or last name to corresponding new name
        func = compose(get_group, case_insensitive_replacer(old[0], new[0]), case_insensitive_replacer(old[1], new[1]))
        
        replacers.append((regex, func))
    return replacers

