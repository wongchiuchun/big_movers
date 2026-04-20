# How to Run the Server

> Your default `python3` (in `~/.browser-use-env/`) does **NOT** have Flask.
> Always use the full path to system Python 3.13 below.

## Start in background (recommended)

Copy-paste this whole block:

```bash
cd "/Users/raywong/Desktop/qullamaggie-study-guide/setup analysis/big_movers"
nohup /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 Big_movers_server.py > server.log 2>&1 &
disown
```

Then open: http://localhost:5051/

The server keeps running after you close the terminal.

## Start in foreground (Ctrl+C to stop)

```bash
cd "/Users/raywong/Desktop/qullamaggie-study-guide/setup analysis/big_movers"
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 Big_movers_server.py
```

## Stop the server

```bash
lsof -ti :5051 | xargs kill
```

## Check if it's running

```bash
lsof -ti :5051
```

Prints a PID number if running, nothing if stopped.

## Watch the logs

```bash
tail -f "/Users/raywong/Desktop/qullamaggie-study-guide/setup analysis/big_movers/server.log"
```

Ctrl+C to stop watching (server keeps running).

## Restart

```bash
lsof -ti :5051 | xargs kill 2>/dev/null
cd "/Users/raywong/Desktop/qullamaggie-study-guide/setup analysis/big_movers"
nohup /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 Big_movers_server.py > server.log 2>&1 &
disown
```

---

## Why the long Python path?

`python3` in your shell points to `~/.browser-use-env/bin/python3` — a virtualenv for another project that doesn't have Flask. The system Python at `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3` has Flask installed, so always use that full path for this project.

To verify:

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -c "import flask; print(flask.__version__)"
```

Should print `3.1.3` (or similar).
