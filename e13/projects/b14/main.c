#include <stdio.h>
#include "config.h"
#include "helper.h"

int main(void) {
    const int alerts = b14_alert_count();
    if (VALUE < 1 || VALUE > 10 || alerts < 0) {
        return 2;
    }
    printf("%d\n", VALUE * alerts);
    return 0;
}
