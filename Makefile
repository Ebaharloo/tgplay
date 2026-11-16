PY := env -u PYTHONPATH .venv/bin/python

.PHONY: test finalize
test finalize:  # full feature suite; non-zero exit on any failure (finalize gate)
	$(PY) -m pytest tests -q
