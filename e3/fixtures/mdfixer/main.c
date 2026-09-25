/* B14 E3 MDFixer fixture.
 *
 * main.c really reads config.h at compile time (#include), but
 * Makefile.before does NOT declare config.h as a prerequisite of main.o.
 * That declaration gap is the MISSING dependency (MD) this sample targets.
 */
#include <stdio.h>
#include "config.h"

int main(void)
{
    printf("%d\n", VALUE);
    return 0;
}
