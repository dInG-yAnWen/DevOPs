#include <stddef.h>
#include "helper.h"

/* Four fixed samples make the count and header-change probe reproducible. */
int b14_alert_count(void) {
    static const int samples[] = {18, 31, 42, 55};
    const int threshold = 50;
    int alerts = 0;
    size_t index;

    for (index = 0; index < sizeof(samples) / sizeof(samples[0]); ++index) {
        if (samples[index] >= threshold) {
            ++alerts;
        }
    }
    return alerts;
}
