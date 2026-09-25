# B14 E3 DRAFT fixture Makefile (course manual sample TinyGreeting).
# Build:  make
# Verify: make test   (runs ./hello; expect stdout "hello E3", exit code 0)
CC     ?= cc
CFLAGS ?= -O2 -Wall

hello: main.o
	$(CC) $(CFLAGS) main.o -o hello

main.o: main.c
	$(CC) $(CFLAGS) -c main.c -o main.o

test: hello
	./hello

clean:
	rm -f main.o hello

.PHONY: test clean
