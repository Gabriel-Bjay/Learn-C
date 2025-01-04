#include <stdio.h>

int main(){
    int myNumbers[] = {20,99,17,62,77};
    printf("%d\n", myNumbers[0]);
    //Changing value of array element
    myNumbers[0] = 100;
    printf("%d\n", myNumbers[0]);//Now outputs 100

    //Finding the length of an array
    int myNum[] = {1,2,3,4,5,6,7,8,9,10};
    int length = sizeof(myNum) / sizeof(myNum[0]);
    printf("The length of the array is %d\n", length);

    //Looping through an array
    int myNums[] = {7,16,28,13,90,52};
    int arrayLength = sizeof(myNums) / sizeof(myNums[0]);
    printf("The array length is %d\n", arrayLength);
    int i;

    for(i = 0; i < arrayLength; i++){
        printf("%d\n", myNums[i]);
    }

    //Calculating average of different ages

    // An array storing different ages
    int ages[] = {20, 22, 18, 35, 48, 26, 87, 70};

    float avg, sum = 0; //Initializing float variable avg and sum
    int j;// Loop counter

    // Get the length of the array
    int ageLength = sizeof(ages) / sizeof(ages[0]);

    // Loop through the elements of the array
    for (j = 0; j < ageLength; j++) {
    sum += ages[j];
    }

    // Calculate the average by dividing the sum by the length
    avg = sum / ageLength;

    // Print the average
    printf("The average age is: %.2f", avg);//Outputs the average age to 2 decimal places

    //Finding the maximum value in an array
    int numbersMax[] = {20,17,29,77,120,2,28};
    int a = 0;
    int arrayLength1 = sizeof(numbersMax) / sizeof(numbersMax[0]);

    for (a = 1; a < arrayLength1; a++) {
        if (numbersMax[0] < numbersMax[a]) {
            numbersMax[0] = numbersMax[a];
        }
    } //Checks the maximum number in the array and returns it as the first element of the array

    printf("The maximum number in the array is: %d\n", numbersMax[0]);// Outputs the maximum number in the array

    //Multidimensional arrays
    int myMatrix[3][4] = { {1, 2, 3, 4}, {5, 6, 7, 8}, {9, 10, 11, 12} };
    printf("%d\n", myMatrix[2][3]); //Outputs 12
    int x, y;

    for (x = 0; x < 3; x++) {
        for (y = 0; y < 4; y++) {
            printf("%d ", myMatrix[x][y]);
        }
        printf("\n");
    }
    return 0;
}