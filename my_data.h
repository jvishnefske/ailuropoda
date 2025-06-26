#ifndef MY_DATA_H
#define MY_DATA_H

#include <stdbool.h> // For bool type
#include <stdint.h>  // For fixed-width integer types

// A simple struct for a point
typedef struct {
    int x;
    float y;
} Point;

// A struct for an address, defined anonymously within Person
struct Address {
    char street[128];
    int number;
    char city[64];
};

// The main Person struct
struct Person {
    char name[64];
    int age;
    bool is_student;
    Point location; // Nested struct
    int scores[5]; // Array of integers
    char* email; // Pointer to char (string) - requires manual memory management for decoding
    uint64_t id;
    double balance;
    struct Address address; // Nested struct defined above
    char notes[256]; // Changed from const char* to char array for simpler codegen/decoding
    int* favorite_number; // Pointer to int - requires manual memory management for decoding
    // void (*callback_func)(); // Function pointer - will be skipped
};

// An empty struct
struct EmptyStruct {};

#endif // MY_DATA_H
