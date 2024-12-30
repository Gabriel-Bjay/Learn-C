#include <stdio.h>

int main() {
    printf("Hello, World!\n");
    // Declare and initialize variables
    int myNum = 5; // Integer (whole number)
    int myOtherNum = 25;   // Integer (whole number)
    int x;
    float myFloatNum = 5.5; // Floating point number
    char myString = 'D';   // Character
    // Assign value of myNum to x
    x = myNum;
    //Adding variables together
    int sum = myNum + myOtherNum;
    int sum2 = sum + x;

    //Student Data
    int studentId = 1738;
    float studentGrade = 73.81;
    // Print the values of the variables
    printf("%d\n", myNum);
    printf("%d\n", sum);
    printf("%d\n", sum2);
    printf("%d\n", studentId);
    printf("%f\n", myFloatNum);
    printf("%f\n", studentGrade);
    printf("%c\n", myString);
    return 0;
}