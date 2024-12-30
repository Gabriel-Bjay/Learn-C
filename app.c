#include <stdio.h>
int main() {
    // Create variables of different data types
    int items = 27;
    float cost_per_item = 12.75;
    char currency = '$';

    float total_cost = items * cost_per_item;
    // Print variables
    printf("Number of items: %d\n", items);
    printf("Cost per Item: %.2f %c\n", cost_per_item, currency);
    printf("Total cost = %.2f %c\n", total_cost, currency);
    return 0;
}