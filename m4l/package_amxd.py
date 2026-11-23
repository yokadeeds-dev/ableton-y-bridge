import os
import zipfile, os, shutil

build_dir = os.path.dirname(os.path.abspath(__file__))
out_path = os.path.join(os.path.expanduser('~'), 'Documents', 'Ableton', 'User Library', 'Presets', 'Audio Effects', 'Max Audio Effect', 'AbletonMCP_Analyzer.amxd')

with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    zf.write(os.path.join(build_dir, 'AbletonMCP_Analyzer.maxpat'), 'AbletonMCP_Analyzer.maxpat')
    zf.write(os.path.join(build_dir, 'ableton_mcp_udp.js'), 'ableton_mcp_udp.js')

print(f"Created: {out_path}")
print(f"Size: {os.path.getsize(out_path)} bytes")
