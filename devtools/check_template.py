#!/usr/bin/env python3

with open('templates/appointments/vanilla.html', 'r', encoding='utf-8') as f:
    content = f.read()

print('=== TEMPLATE ANALYSIS ===')

print('\n1. Lucide Library Check:')
if 'unpkg.com/lucide' in content:
    print('[OK] CDN link found')
else:
    print('[ERROR] CDN link missing')

print('\n2. createIcons usage:')
if 'lucide.createIcons' in content:
    print('[OK] createIcons call found')
    count = content.count('lucide.createIcons()')
    print(f'  - {count} calls found')
else:
    print('[ERROR] createIcons call missing')

print('\n3. Error messages in template:')
error_patterns = ['Error Loading Application', 'Could not load application data', 'lucide is not defined']
for pattern in error_patterns:
    count = content.count(pattern)
    print(f'  - "{pattern}": {count} occurrences')

print('\n4. JSON script tags:')
json_scripts = ['appointments-data', 'patients-data', 'doctors-data']
for script_id in json_scripts:
    if f'id="{script_id}"' in content:
        print(f'  [OK] {script_id} script tag found')
    else:
        print(f'  [ERROR] {script_id} script tag missing')

print('\n5. Raw blocks:')
if '{% raw %}' in content and '{% endraw %}' in content:
    print('[OK] Raw blocks properly configured')
else:
    print('[ERROR] Raw blocks missing or incomplete')

print('\n6. App root element:')
if '<div id="app-root"></div>' in content:
    print('[OK] App root element found')
else:
    print('[ERROR] App root element missing')
