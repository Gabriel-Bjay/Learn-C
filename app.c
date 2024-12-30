#include <stdio.h>
int main() {
    //If else statements
    int a = 111;
    int b = 100;
    if(a > b){
        printf("%d is greater\n", a);
    }else{
        printf("%d is greater\n", b);
    }
    //If else if statements
    int age = -17;
    int votingAge = 18;
    if(age >= votingAge){
        printf("You are eligible to vote\n");
    }else if(age < votingAge && age > 0){
        printf("You are not eligible to vote\n");
    }else{
        printf("Invalid age\n");
    }
    //Nested if else statements
    int num = 30;
    if (num > 0) {
        printf("%d is positive.\n", num);
        if (num % 2 == 0) {
            printf("%d is even.\n", num);
        } else { printf("%d is odd.\n", num);
        }
    } else {
        printf("%d is negative or zero.\n", num);
    }
    //shorthand if statements
    int time = 20;
    (time <= 18) ? printf("Good day.\n") : printf("Good evening.\n");
    return 0;
}