#!/bin/sh
git grep -L SPDX-License-Identifier \
	':*.py' \
	':*.pyi' \
	':*.c'
test $? -ne 0
