#!/usr/bin/env python3

# MMOBS: Minecraft MOdpack Buildng System

# Copyleft (C) Alexandria Pettit
# GNU GPL v3! Use this code for nice things!

# Author's note: I wouldn't have to write this script if CurseForge
# wasn't a shitty distribution platform with no decent API documentation and
# a crap API design to boot.

# Honestly, it's times like this that I wish we could go back to plain old
# HTTP directory access. This didn't need to be this complicated.

#TODO: Add basic logging
#TODO: Add proper metadata parsing so that it can give a specific line when there's an error.

from bs4 import BeautifulSoup
from glob import glob
from urllib.parse import unquote
import sys, os, requests, shutil

# Example URL format:
# https://minecraft.curseforge.com/projects/projecte/files?filter-game-version=2020709689%3A4449
# Formatting: [root url]/[project name]/files?filter-game-version=[bullshit game version string]
url_root = 'https://minecraft.curseforge.com'
# r = URL root, p = project name, v = target game version
url_f = '{r}/projects/{p}/files?filter-game-version={v}'


# Here are the classes we look for to find the "mod download" sublink.
# There is also a link at the top for downloading the absolute latest release (regardless of version),
# but we want to avoid that link for obvious reasons.
classes_in_target_link = ('button', 'tip', 'fa-icon-download', 'icon-only')


# Dictionary of bullshit game version strings used by forge.
game_versions = {'1.12.2':'2020709689%3A6756',
                 '1.12.1':'2020709689%3A6711'}

# Checks whether A is a subset of B.
# I'm pretty sure there's a built-in Python function to do this,
# but I was too lazy to look it up.
def subset(a, b):
    try:
        for item in a:
            if not item in b:
                return False
    # TypeError happens when handling a None,
    # e.g. when link had no classes
    except TypeError:
        return False
    # reachable only if none of the items in A were in B
    return True

# Iterate through links looking for one matching our list of classes
def curseforge_find_dl_link(html_page):
    soup = BeautifulSoup(html_page, 'html.parser')
    for link in soup.find_all('a'):
        if subset(classes_in_target_link, link.get('class')):
            return link

# Simple INI parser
def sini_parse(fhandle, required_categories, permitted_categories = ''):
    
    # Here we store data in the form {'derp':[foo, bar, baz]}
    # where derp is the category and foo, bar, baz are a list of elements
    config = {}
    
    # Here we store the current category
    category = ''
    
    error = False
    
    # Iterate through all lines in file
    for i, line in enumerate( fhandle.readlines() ):
        line = line.strip()
        
        # Skip all newlines and comments.
        if not line or line[0] == '#':
            continue
        
        # Identify category lines, e.g. [foo].
        if line[0] == '[' and line[-1] == ']':
            category = line[1:-1]
            if permitted_categories and not category in permitted_categories:
                print('Error: category "%s" on line %i not in permitted categories.' %
                (category, i))
                error = True
            config[category] = []
            
            # Check category off our "required categories list"
            if category and category in required_categories:
                target_index = required_categories.index(category)
                del required_categories[target_index]
            continue
        
        # If category isn't set for our current context,
        # it means there was no category line above this entry.
        # Refuse to run until the user fixes that.
        if not category:
            print('Error identifying category for line %i. Check above category definitions.' % i)
            error = True
        else:
            # Add the line to the current category
            config[category] += [line]
        
    if required_categories:
        print('Error: Required categories are missing from config file:')
        print('\n'.join(required_categories))
        error = True
    
    if error:
        print('Parsing of config file completed with errors. Exiting!')
        exit(1)
    
    return config

# Name/path of config file to load.
config_file = 'modpack.conf'

# Target Minecraft mod directory. This is where to install/update mods.
mods_dir = 'mods'

# Place to dump old/unrecognized Minecraft mods.
# By default, will be interpreted as relative to mods directory. e.g., .minecraft/mods/trash
# Can be overriden with absolute path.
trash_dir = 'trash'

modfile_name_list = []

known_categories = ['mods', 'whitelist', 'metadata']

if __name__ == '__main__':
    # Yes, I'm aware of optargs. But it's a pain to use IMO.
    flag = ''
    for arg in sys.argv:
        # Anything beginning with '-' is a flag, and we store it to know
        # the meaning of the value coming after
        if arg[0] == '-':
            flag = arg
        elif flag in ('-c', '--modpack-config'):
            config_file = arg
        elif flag in ('-d', '--mods-dir'):
            mods_dir = arg
        elif flag in ('-t', '--trash-dir'):
            trash_dir = arg

    s = requests.Session()
    
    print('Loading "%s"...' % config_file)
    modpack = sini_parse(open(config_file), known_categories, known_categories)
    
    metadata = {}
    for line in modpack['metadata']:
        if not ': ' in line:
            print('Syntax error in metadata on line... um... whatever it was.')
            exit(1)
        line = line.split(': ')
        metadata[line[0]] = line[1]
        
    print('Loaded modpack config file for game version "%s"' %
    metadata['game_version'])
        
    for mod in modpack['mods']:
        url = url_f.format(
                r = url_root,
                p = mod,
                v = game_versions[metadata['game_version']] )
        print('Now querying: ' + url)
        # Request download page for mod.
        r = s.get(url)

        # If we fail to get this URL, notify user and skip downloading the mod.
        if r.status_code != requests.codes.ok:
            print('Error retrieving page for mod "%s"!' % mod)
            continue

        dl_link = curseforge_find_dl_link(r.text)
        if not dl_link:
            print('Could not find download link for "%s"!' % mod)
            print('Perhaps it doesn\'t have a download marked for the specified Minecraft version?')
            exit(1)

        url_end = dl_link.get('href')
        url = url_root + url_end
        print('Mod URL: ' + url)

        # Next request! This time, we're putting in the request for the actual mod file.
        del r
        r = s.get(url, stream=True)

        # If we fail to retrieve jar file, notify user and... you know the drill.
        if r.status_code != requests.codes.ok:
            print('Error retrieving jar file for mod "%s"!' % mod)
            continue
            
        # Get the last URL in r.history -- this is the ultimate one we 
        # were redirected to.
        final_url = r.history[-1].url
        print('We were redirected to "%s"' % final_url)
        
        # The full name of the jar.
        # This lets us confirm whether it's a new version or not.
        modfile_name = unquote(os.path.basename(final_url))

        modfile_name_list += [modfile_name]
        
        modfile_path = os.path.join(mods_dir, modfile_name) 

        print('Download file\'s path is "%s"' % modfile_path)

        if os.path.exists(modfile_path):
            print('File "%s" already exists. Skipping mod download!' %
            modfile_path)
            continue
        
        print('File download is in progress!')
        

        with open(modfile_path, 'wb') as output:
            shutil.copyfileobj(r.raw, output)
        del r

        print('Download complete!')

    # Create our trash dir if it doesn't exist
    os.makedirs(trash_dir, exist_ok=True)

    modfile_name_list += modpack['whitelist']
    
    print('Anything not matching the following files will be deleted:')
    print(modfile_name_list)
    
    # Move all .jar files we don't recognize into trash dir.
    # This heuristic ensures all old mod
    # versions don't get left in the root mods directory.
    for f in glob(os.path.join(mods_dir, '*.jar')):
        if not os.path.basename(f) in modfile_name_list:
            print('Moving "%s" to trash dir...' % f)
            shutil.move(f, trash_dir)
