#include<stdio.h>
int main(){
    int month = 3;
    switch (month)
    {
    case 1:
        printf("January\n");
        break;
    case 2:
        printf("February\n");
        break;
    case 3:
        printf("March\n");
        break;
    case 4:
        printf("April\n");
        break;
    case 5:
        printf("May\n");
        break;
        // Add more cases for other months
    default:
        break;
        // If the month is not between 1 and 5, print an error message
        printf("Invalid month\n");
    }
    return 0;
}