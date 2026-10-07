import os
outfile = os.path.join(os.path.dirname(__file__), 'simple_test_output.txt')
with open(outfile, 'w') as f:
    f.write('FREECADCMD WORKS\n')
os._exit(0)
