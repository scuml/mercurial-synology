.PHONY: package deploy preview preview-web clean test

PYTHON ?= $(shell for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3 python3; do \
	"$$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 9))' >/dev/null 2>&1 && { printf '%s' "$$candidate"; break; }; \
	done)

package:
	./build.sh

deploy:
	./deploy.sh $(TARGET)

test:
	$(PYTHON) -m unittest discover -s tests -v

preview:
	$(PYTHON) tools/preview_ext.py

preview-web:
	$(PYTHON) tools/preview.py

clean:
	rm -rf build
