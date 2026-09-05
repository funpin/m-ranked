import re, sys, json, collections, pathlib

src = pathlib.Path(sys.argv[1]).read_text()
HDR = re.compile(r'^--\n-- Name: (?P<name>.*?); Type: (?P<type>[A-Z ]+); Schema: (?P<schema>[^;]*);.*?\n--\n', re.M)
marks = list(HDR.finditer(src))
stmts = []
for i, m in enumerate(marks):
    end = marks[i+1].start() if i+1 < len(marks) else len(src)
    body = src[m.end():end].strip()
    if body:
        stmts.append({'name': m['name'].strip(), 'type': m['type'].strip(),
                      'schema': m['schema'].strip(), 'body': body})

PART = re.compile(r'_(?:19|20)\d{2}_\d{2}\b|_default\b')
TARGET = re.compile(r'^(?:CREATE (?:UNIQUE )?INDEX \S+ ON (?:ONLY )?|ALTER TABLE (?:ONLY )?|CREATE TABLE |CREATE TRIGGER \S+ [A-Z ]+ ON )([a-z_]+\.[a-z_0-9]+)', re.M)

def target(s):
    m = TARGET.search(s['body'])
    return m.group(1) if m else ''

def is_child(s):
    if PART.search(s['name']): return True
    t = target(s)
    return bool(t and PART.search(t))

def is_attach(s):
    return 'ATTACH PARTITION' in s['body']

kept, childs, attach = [], [], []
for s in stmts:
    if is_child(s): childs.append(s)
    elif is_attach(s): attach.append(s)
    else: kept.append(s)

print("total:", len(stmts), "| children:", len(childs), "| attach:", len(attach), "| kept:", len(kept))
print()
for t, c in collections.Counter(s['type'] for s in kept).most_common():
    print(f"  {t:22} {c}")
pathlib.Path(sys.argv[2]).write_text(json.dumps(kept, ensure_ascii=False, indent=1))
