# To build:
#
# CROSS_COMPILE=aarch64-linux-gnu- make
#

CROSS_COMPILE?=aarch64-linux-gnu-
CC=$(CROSS_COMPILE)gcc
CFLAGS=-static -lc

librate-freqs: librate_freqs.c
	$(CC) -std=c99 -Wall -Werror -static -o $@ $<
