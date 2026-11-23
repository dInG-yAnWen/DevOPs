CC = gcc
CFLAGS = -O0
EXPECTED_OUTPUT ?= 1

.PHONY: all clean test
all: app

app: main.o helper.o
	$(CC) main.o helper.o -o app

main.o: main.c config.h helper.h
	$(CC) $(CFLAGS) -Wall -Wextra -Werror -std=c99 -c main.c -o main.o

helper.o: helper.c helper.h
	$(CC) $(CFLAGS) -Wall -Wextra -Werror -std=c99 -c helper.c -o helper.o

test: app
	@set -eu; output=$$(mktemp); trap 'rm -f "$$output"' EXIT HUP INT TERM; \
	./app > "$$output"; \
	printf '%s\n' '$(EXPECTED_OUTPUT)' | cmp -s - "$$output"; \
	printf 'PASS: exact output %s, exit 0\n' '$(EXPECTED_OUTPUT)'

clean:
	rm -f main.o helper.o app app.exe
