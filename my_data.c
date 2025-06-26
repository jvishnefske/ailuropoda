#include "my_data.h"
#include "cbor_generated.h"
#include <stdio.h>
#include <stdlib.h> // For malloc, free
#include <string.h> // For strlen, strcpy
#include <stdbool.h> // For bool

// Helper to print hex buffer
void print_hex_buffer(const char* label, const uint8_t* buffer, size_t len) {
    printf("%s (%zu bytes): ", label, len);
    for (size_t i = 0; i < len; ++i) {
        printf("%02X ", buffer[i]);
    }
    printf("\n");
}

int main() {
    // --- 1. Prepare original data ---
    struct Person original_person = {0}; // Initialize all members to 0/NULL

    strcpy(original_person.name, "Alice Smith");
    original_person.age = 30;
    original_person.is_student = true;

    original_person.location.x = 10;
    original_person.location.y = 20.5f;

    original_person.scores[0] = 90;
    original_person.scores[1] = 85;
    original_person.scores[2] = 92;
    original_person.scores[3] = 78;
    original_person.scores[4] = 95;

    // Allocate and set email
    original_person.email = (char*)malloc(strlen("alice@example.com") + 1);
    if (original_person.email) {
        strcpy(original_person.email, "alice@example.com");
    } else {
        fprintf(stderr, "Failed to allocate memory for email.\n");
        return 1;
    }

    original_person.id = 1234567890ULL;
    original_person.balance = 12345.678;

    strcpy(original_person.address.street, "Main St");
    original_person.address.number = 123;
    strcpy(original_person.address.city, "Anytown");

    strcpy(original_person.notes, "Some notes about Alice."); // Now a char array

    // Allocate and set favorite_number
    original_person.favorite_number = (int*)malloc(sizeof(int));
    if (original_person.favorite_number) {
        *original_person.favorite_number = 42;
    } else {
        fprintf(stderr, "Failed to allocate memory for favorite_number.\n");
        free(original_person.email);
        return 1;
    }

    printf("--- Original Person Data ---\n");
    printf("Name: %s\n", original_person.name);
    printf("Age: %d\n", original_person.age);
    printf("Is Student: %s\n", original_person.is_student ? "true" : "false");
    printf("Location: (%d, %.1f)\n", original_person.location.x, original_person.location.y);
    printf("Scores: %d, %d, %d, %d, %d\n", original_person.scores[0], original_person.scores[1], original_person.scores[2], original_person.scores[3], original_person.scores[4]);
    printf("Email: %s\n", original_person.email);
    printf("ID: %llu\n", original_person.id);
    printf("Balance: %.3f\n", original_person.balance);
    printf("Address: %d %s, %s\n", original_person.address.number, original_person.address.street, original_person.address.city);
    printf("Notes: %s\n", original_person.notes);
    printf("Favorite Number: %d\n", *original_person.favorite_number);
    printf("\n");

    // --- 2. Encode data to CBOR ---
    uint8_t buffer[512]; // Increased buffer size for complex struct
    CborEncoder encoder;
    cbor_encoder_init(&encoder, buffer, sizeof(buffer), 0);

    printf("Encoding Person struct...\n");
    if (!encode_Person(&original_person, &encoder)) {
        fprintf(stderr, "Failed to encode Person struct.\n");
        free(original_person.email);
        free(original_person.favorite_number);
        return 1;
    }

    size_t encoded_len = cbor_encoder_get_buffer_size(&encoder, buffer);
    print_hex_buffer("Encoded CBOR", buffer, encoded_len);
    printf("\n");

    // --- 3. Decode data from CBOR ---
    struct Person decoded_person = {0}; // Initialize to zero
    // For pointers in decoded_person, we need to allocate memory before decoding
    decoded_person.email = (char*)malloc(128); // Max size for email
    if (!decoded_person.email) {
        fprintf(stderr, "Failed to allocate memory for decoded email.\n");
        free(original_person.email);
        free(original_person.favorite_number);
        return 1;
    }
    decoded_person.favorite_number = (int*)malloc(sizeof(int));
    if (!decoded_person.favorite_number) {
        fprintf(stderr, "Failed to allocate memory for decoded favorite_number.\n");
        free(original_person.email);
        free(original_person.favorite_number);
        free(decoded_person.email);
        return 1;
    }

    CborParser parser;
    CborValue it;
    cbor_parser_init(buffer, encoded_len, 0, &parser, &it);

    printf("Decoding Person struct...\n");
    if (!decode_Person(&decoded_person, &it)) {
        fprintf(stderr, "Failed to decode Person struct.\n");
        free(original_person.email);
        free(original_person.favorite_number);
        free(decoded_person.email);
        free(decoded_person.favorite_number);
        return 1;
    }

    printf("--- Decoded Person Data ---\n");
    printf("Name: %s\n", decoded_person.name);
    printf("Age: %d\n", decoded_person.age);
    printf("Is Student: %s\n", decoded_person.is_student ? "true" : "false");
    printf("Location: (%d, %.1f)\n", decoded_person.location.x, decoded_person.location.y);
    printf("Scores: %d, %d, %d, %d, %d\n", decoded_person.scores[0], decoded_person.scores[1], decoded_person.scores[2], decoded_person.scores[3], decoded_person.scores[4]);
    printf("Email: %s\n", decoded_person.email);
    printf("ID: %llu\n", decoded_person.id);
    printf("Balance: %.3f\n", decoded_person.balance);
    printf("Address: %d %s, %s\n", decoded_person.address.number, decoded_person.address.street, decoded_person.address.city);
    printf("Notes: %s\n", decoded_person.notes);
    printf("Favorite Number: %d\n", decoded_person.favorite_number ? *decoded_person.favorite_number : -1);
    printf("\n");

    // --- 4. Verify data (simple check) ---
    bool success = true;
    if (strcmp(original_person.name, decoded_person.name) != 0) { printf("Name mismatch!\n"); success = false; }
    if (original_person.age != decoded_person.age) { printf("Age mismatch!\n"); success = false; }
    if (original_person.is_student != decoded_person.is_student) { printf("Is Student mismatch!\n"); success = false; }
    if (original_person.location.x != decoded_person.location.x) { printf("Location X mismatch!\n"); success = false; }
    if (original_person.location.y != decoded_person.location.y) { printf("Location Y mismatch!\n"); success = false; }
    for (int i = 0; i < 5; ++i) {
        if (original_person.scores[i] != decoded_person.scores[i]) { printf("Score %d mismatch!\n", i); success = false; }
    }
    if (strcmp(original_person.email, decoded_person.email) != 0) { printf("Email mismatch!\n"); success = false; }
    if (original_person.id != decoded_person.id) { printf("ID mismatch!\n"); success = false; }
    if (original_person.balance != decoded_person.balance) { printf("Balance mismatch!\n"); success = false; }
    if (strcmp(original_person.address.street, decoded_person.address.street) != 0) { printf("Address Street mismatch!\n"); success = false; }
    if (original_person.address.number != decoded_person.address.number) { printf("Address Number mismatch!\n"); success = false; }
    if (strcmp(original_person.address.city, decoded_person.address.city) != 0) { printf("Address City mismatch!\n"); success = false; }
    if (strcmp(original_person.notes, decoded_person.notes) != 0) { printf("Notes mismatch!\n"); success = false; }
    if (original_person.favorite_number && decoded_person.favorite_number && *original_person.favorite_number != *decoded_person.favorite_number) { printf("Favorite Number mismatch!\n"); success = false; }
    else if ((original_person.favorite_number && !decoded_person.favorite_number) || (!original_person.favorite_number && decoded_person.favorite_number)) { printf("Favorite Number pointer mismatch!\n"); success = false; }


    if (success) {
        printf("Verification: SUCCESS! Original and decoded data match.\n");
    } else {
        printf("Verification: FAILED! Original and decoded data do NOT match.\n");
    }

    // --- 5. Clean up allocated memory ---
    free(original_person.email);
    free(original_person.favorite_number);
    free(decoded_person.email);
    free(decoded_person.favorite_number);

    return success ? 0 : 1;
}
