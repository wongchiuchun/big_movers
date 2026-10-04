# Vendored ABIDES

Source: https://github.com/jpmorganchase/abides-jpmc-public
Revision: f9cbe51342b7dedd9587e4e069040d68a5c6477f
License: BSD 3-Clause; both upstream license files are retained as
ABIDES-LICENSE and ABIDES-LICENSE.txt.

The abides_core and abides_markets packages are copied from this revision.
Local adaptation: abides_markets/agents/__init__.py imports only the three base
classes used here, avoiding optional legacy agent/model imports.
Matching and kernel source are unchanged. Custom subclasses live outside vendor/.
No Gym/Ray/pomegranate dependency is used by this trainer.
