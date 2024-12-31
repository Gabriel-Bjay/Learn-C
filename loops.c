#include<stdio.h>

int main(){
    //while loop
    int i = 0;
    while (i < 5)
    {
        printf("%d\n", i);
        i++;
    }
    //do while loop
    int j = 5;
    do{
        printf("%d\n", j);
        j++;
    }
    while (j < 11);
    //while loop example
    int countdown = 10;
    while (countdown > 0) {
        printf("%d\n", countdown);
        countdown = countdown - 1;
    }
    printf("Blastoff!\n");
    // while loop example including if...else statement
    int dice = 1;

    while (dice <= 6) {
    if (dice < 6) {
        printf("No Yatzy\n");
    } else {
        printf("Yatzy!\n");
    }
    dice = dice + 1;
    }
    //Reversing numbers using while loops
    int numbers = 12345;  // A variable with some specific numbers
    int revNumbers = 0;  // A variable to store the reversed number
    // Reverse and reorder the numbers
    while (numbers) {
        // Get the last number of 'numbers' and add it to 'revNumber'
        revNumbers = revNumbers * 10 + numbers % 10;
        // Remove the last number of 'numbers'
        numbers /= 10;
    }

    // Output the reversed numbers
    printf("%d", revNumbers);

    //For loops
    int k;
    for (k = 100; k <= 110; k++) {
        printf("%d\n", k);
    }
    //Nested loops
    int l, m;

    // Outer loop
    for (l = 1; l <= 2; ++l) {
    printf("Outer: %d\n", l);  

    // Inner loop
    for (m = 1; m <= 3; ++m) {
        printf(" Inner: %d\n", m);  
    }
    }
    return 0;
}