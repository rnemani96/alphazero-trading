import zipfile
import xml.etree.ElementTree as ET

def extract():
    with zipfile.ZipFile('doc/alphazero_masterref.docx') as z:
        xml_content = z.read('word/document.xml')
    root = ET.fromstring(xml_content)
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    text = ' '.join(node.text for node in root.findall('.//w:t', ns) if node.text)
    with open('doc/master_ref_clean.txt', 'w', encoding='utf-8') as f:
        f.write(text)
    print('SUCCESS')

extract()
