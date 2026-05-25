import sys, json, struct
from pathlib import Path

def fix_glb(path_str):
    p = Path(path_str)
    if not p.exists(): return
    with open(p, 'rb') as f:
        data = bytearray(f.read())
    if data[0:4] != b'glTF': return

    jlen = struct.unpack_from('<I', data, 12)[0]
    jstr = data[20:20+jlen].decode('utf-8').rstrip(' \t')
    j = json.loads(jstr)
    
    meshes = j.get('meshes', [])
    if len(meshes) <= 1: return
    
    old_node = j['nodes'][0]
    matrix = old_node.get('matrix')
    new_nodes = []
    for i in range(len(meshes)):
        n = {'mesh': i, 'name': f'LOD{i+1}'}
        if matrix: n['matrix'] = matrix
        new_nodes.append(n)
        
    j['nodes'] = new_nodes
    j['scenes'][0]['nodes'] = list(range(len(new_nodes)))
    
    new_jstr = json.dumps(j).encode('utf-8')
    padding_len = (4 - (len(new_jstr) % 4)) % 4
    new_jstr += b' ' * padding_len
    
    new_data = bytearray()
    new_data.extend(data[:12])
    new_data.extend(struct.pack('<I', len(new_jstr)))
    new_data.extend(b'JSON')
    new_data.extend(new_jstr)
    
    bin_off = 20 + jlen
    if bin_off < len(data):
        new_data.extend(data[bin_off:])
        
    struct.pack_into('<I', new_data, 8, len(new_data))
    
    with open(p, 'wb') as f:
        f.write(new_data)
    print(f'Fixed {p.name}: now has {len(meshes)} nodes.')

for f in Path('./SRS Workspace/modeles').glob('*_X.glb'):
    fix_glb(f)
