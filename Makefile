.PHONY: help build clean run

help:
	@echo "Please use \`make <target>' where <target> is one of:"
	@echo "  build - to build the site (converts *.md -> *.html)"
	@echo "  clean - to remove build files"
	@echo "  run   - to run a development server at http://localhost:4000"

build:
	virtualenv venv
	venv/bin/pip install -r requirements.txt
ifeq ("${BASEURL}", "")
	venv/bin/python build.py
else
	venv/bin/python build.py --baseurl ${BASEURL}
endif

clean:
	find . -name "*.html" -exec rm -rf {} \;
	rm -rf venv

run:
	python3 -m http.server 4000
