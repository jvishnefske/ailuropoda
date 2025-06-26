#ifndef SIMPLE_DATA_H
#define SIMPLE_DATA_H

#include <stdint.h>
#include <stdbool.h>

// A simple struct for integration testing
struct SimpleData {
    int32_t id;
    char name[32];
    bool is_active;
    float temperature;
    uint8_t flags[4];
};

// A struct with a nested struct and a pointer
struct NestedData {
    struct SimpleData inner_data;
    char* description; // Assumed to be pre-allocated for decoding
    int32_t value;
};

#endif // SIMPLE_DATA_H
