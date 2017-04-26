/*
 *    Copyright 2017 ARM Limited
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at

 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 *
 * Designed to quickly alternate between two CPU freqeuencies using the
 * userspace governor. Arguments are:
 *
 *   cpu freq1 freq2 interval_us num_loops
 *
 * Run me as root.
 */

#define _DEFAULT_SOURCE /* To make unistd.h work */

#include <argp.h>
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

/* Write the scaling_setspeed file or die trying */
void write_freq(int freq_fd, const char *freq, int freq_len)
{
        int ret = write(freq_fd, freq, freq_len);
        if (ret < 0) {
                perror("Couldn't set freq");
                exit(errno);
        }
}

/* Get the time from clock_gettime or die trying */
void gettime(struct timespec *ts)
{
        int ret = clock_gettime(CLOCK_MONOTONIC, ts);
        if (ret) {
                perror("clock_gettime failed");
                exit(1);
        }
}

#define NSECS_PER_SEC (1000 * 1000 * 1000)

/* Keep the CPU busy for so many microseconds */
void spend_time(int us)
{
        struct timespec end, now;
        long ns = us * 1000;

        /* Work out a timespec for when we're done looping */
        gettime(&end);
        end.tv_sec  += (ns / NSECS_PER_SEC);
        end.tv_nsec += (ns % NSECS_PER_SEC);
        if (end.tv_nsec >= NSECS_PER_SEC) {
                /* Tick over 1 second */
                end.tv_sec++;
                end.tv_nsec -= NSECS_PER_SEC;
        }

        do {
                gettime(&now);
        } while (now.tv_sec < end.tv_sec || now.tv_nsec < end.tv_nsec);
}

/* Alternatve quickly between the two frequencies */
void librate(int freq_fd, const char *freq1, const char *freq2,
             int interval_us, int num_loops)
{
        int freq1_len = strlen(freq1), freq2_len = strlen(freq2);
        for (int i = 0; i < num_loops; i++) {
                write_freq(freq_fd, freq1, freq1_len);
                spend_time(interval_us);
                write_freq(freq_fd, freq2, freq2_len);
                spend_time(interval_us);
        }
}

/* Parse an integer from a string or die trying */
int parse_int(const char *str, const char *err_msg)
{
        char *endptr;
        int ret = strtol(str, &endptr, 0);
        if (endptr == str) {
                perror(err_msg);
                exit(1);
        }
        return ret;
}

int main(int argc, char **argv)
{
        int ret;

        if (argc < 6) {
                fputs("Args are <cpu> <freq1> <freq2> <interval_us> <loops>\n",
                      stderr);
                exit(1);
        }

        int cpu = parse_int(argv[4], "Invalid CPU");
        const char *freq1 = argv[2], *freq2 = argv[3];
        int interval_us = parse_int(argv[4], "Invalid interval");
        int num_loops = parse_int(argv[5], "Invalid loop count");

        /*
         * Set up cpufreq file descriptors
         */

        const char fmt[] = "/sys/devices/system/cpu/cpu%d/cpufreq/scaling_%s";
        char path[sizeof(fmt) + 32];

        snprintf(path, sizeof(path), fmt, cpu, "governor");
        int gov_fd = open(path, O_WRONLY);
        if (gov_fd < 1) {
                fprintf(stderr, "Failed to open %s\n", path);
                perror("Failed to set up governor");
                exit(errno);
        }
        const char *gov = "userspace\n";
        ret = write(gov_fd, gov, strlen(gov));
        if (ret < 0) {
                perror("Couldn't set governor");
                exit(errno);
        }

        snprintf(path, sizeof(path), fmt, cpu, "setspeed");
        int freq_fd = open(path, O_WRONLY);
        if (!freq_fd) {
                perror("Failed to open scaling_setspeed file");
                exit(errno);
        }

        printf("Switching from %s to %s %d times with %dus interval",
               freq1, freq2, num_loops, interval_us);
        printf(" (Should take about %d seconds)\n", 2 * num_loops * interval_us / 1000000);
        librate(freq_fd, freq1, freq2, interval_us, num_loops);

        return 0;
}
