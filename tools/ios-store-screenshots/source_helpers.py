"""Bind only named pure functions from exact frozen source; no old process runner."""
import ast,types,hashlib,re,struct,zlib
import io_boundary as io

def load(relative,names,extra):
 rows=io.json_read(io.REPO/'tools/ios-store-screenshots/base-manifest.json',256000)
 row=next(r for r in rows if r['path']==relative);raw=io.read(io.REPO/relative,row['bytes'])
 if hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('Frozen pure helper source differs')
 nodes=[n for n in ast.parse(raw).body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
 if {n.name for n in nodes}!=set(names):raise ValueError('Frozen pure helper shape differs')
 values={'hashlib':hashlib,'re':re,'struct':struct,'zlib':zlib,**extra}
 exec(compile(ast.Module(body=nodes,type_ignores=[]),relative,'exec'),values)
 return types.SimpleNamespace(**{name:values[name] for name in names})
def require(value,message):
 if not value:raise ValueError(message)
def bootstatus(raw,expected):return load('scripts/uikit_managed_tests.py',['completed_bootstatus'],{'require':require}).completed_bootstatus(raw,expected)
def fixture():return load('scripts/original_design_gate.py',['fixture_png'],{}).fixture_png()
