#!/bin/bash

sphinx-build -M html build/documentation/ build/documentation/_build
python3 -m http.server --directory build/documentation/_build/html
