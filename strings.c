#include <stdio.h>
#include <string.h> // for using the string functions function

int main(){
    char greeting[] = "Hello Universe!!";
    int i;
    printf("%s\n", greeting);
    greeting [0] = 'W'; // changing the first character of the string
    printf("%s\n", greeting);

    // string length
    int length = strlen(greeting);
    printf("Length of the string: %d\n", length);
    for (i = 0; i < length ; i++)
    {
        printf("%c\n", greeting[i]);
    }

    // string concatenation
    char str1[20] = "Hello ";
    char str2[] = "World";
    strcat(str1, str2);
    printf("Concatenated string: %s\n", str1);

    // string comparison
    char str3[] = "Hello";
    char str4[] = "Hello";
    int result = strcmp(str3, str4);
    if (result == 0)
    {
        printf("Strings are equal\n");
    } else {
        printf("Strings are not equal\n");
    }

    // string copy
    char str5[20];
    strcpy(str5, str1);
    printf("Copied string: %s\n", str5);

    // string substring
    char str6[] = "Hello World";
    char subStr[10];
    strncpy(subStr, str6, 5);
    subStr[5] = '\0'; // making sure the substring is null terminated
    printf("Substring: %s\n", subStr);

    // integer to string conversion
    int num2 = 456;
    char str8[10];
    sprintf(str8, "%d", num2);
    printf("Converted string: %s\n", str8);

    // Getting user input
    // Create a string
    char fullName[30];

    // Ask the user to input some text (full name)
    printf("Type your full name and press enter: \n");

    // Get the text
    fgets(fullName, sizeof(fullName), stdin);

    // Output the text
    printf("Hello %s", fullName);

    //Creating variable to store input from user 
    int myNum;
    //Ask user to type in number
    printf("Type in a number: \n");
    //Reading user input and saving using scanf function
    scanf("%d", &myNum);
    //Printing the number
    printf("Your number is: %d\n", myNum);

    return 0;
}