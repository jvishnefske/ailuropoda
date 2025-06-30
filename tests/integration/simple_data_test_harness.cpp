#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include "doctest/doctest.h"
#include <string.h> // For memset, strcpy, memcmp
#include <stdlib.h> // For malloc, free
#include <vector> // For std::vector (if needed, although not explicitly used in the original C test)

// Include generated CBOR code and original header
#include "cbor_generated.h"
#include "simple_data.h" // Relative to the test harness, as it's in the same `tests/integration` dir

// Include TinyCBOR for direct usage if needed by test logic
#include "tinycbor/cbor.h"

TEST_CASE("SimpleData encoding and decoding roundtrip") {
    MESSAGE("Starting SimpleData encoding and decoding test.");

    struct SimpleData test_data = {
        .id = 123,
        .name = "TestName",
        .is_active = true,
        .temperature = 25.5f,
        .flags = {1, 2, 3, 4}
    };

    uint8_t buffer[256];
    CborEncoder encoder;
    cbor_encoder_init(&encoder, buffer, sizeof(buffer), 0);

    // Encode
    CHECK(encode_SimpleData(&test_data, &encoder));
    size_t encoded_len = cbor_encoder_get_buffer_size(&encoder, buffer);
    MESSAGE("SimpleData encoded successfully. Size: " << encoded_len << " bytes");

    // Decode
    struct SimpleData decoded_data;
    memset(&decoded_data, 0, sizeof(struct SimpleData)); // Initialize to zeros

    CborParser parser;
    CborValue it;
    CborError err = cbor_parser_init(buffer, encoded_len, 0, &parser, &it);
    CHECK_EQ(err, CborNoError);

    CHECK(decode_SimpleData(&decoded_data, &it));
    MESSAGE("SimpleData decoded successfully.");

    // Assertions
    CHECK_EQ(decoded_data.id, test_data.id);
    CHECK_EQ(strcmp(decoded_data.name, test_data.name), 0);
    CHECK_EQ(decoded_data.is_active, test_data.is_active);
    // Floats require approximate comparison
    CHECK_EQ(decoded_data.temperature, doctest::Approx(test_data.temperature));
    CHECK_EQ(memcmp(decoded_data.flags, test_data.flags, sizeof(test_data.flags)), 0);
}

TEST_CASE("NestedData encoding and decoding roundtrip") {
    MESSAGE("Starting NestedData encoding and decoding test.");

    // Original data for NestedData
    struct NestedData original_nested = {
        .inner_data = {
            .id = 456,
            .name = "NestedItem",
            .is_active = false,
            .temperature = 99.9f,
            .flags = {5, 6, 7, 8}
        },
        .description = (char*)malloc(256), // Allocate memory for description
        .value = 789
    };
    REQUIRE(original_nested.description != nullptr); // Ensure allocation succeeded
    strcpy(original_nested.description, "This is a nested description.");

    uint8_t nested_buffer[512];
    CborEncoder nested_encoder;
    cbor_encoder_init(&nested_encoder, nested_buffer, sizeof(nested_buffer), 0);

    // Encode
    CHECK(encode_NestedData(&original_nested, &nested_encoder));
    size_t nested_encoded_len = cbor_encoder_get_buffer_size(&nested_encoder, nested_buffer);
    MESSAGE("NestedData encoded successfully. Size: " << nested_encoded_len << " bytes");

    // Decode
    struct NestedData decoded_nested;
    memset(&decoded_nested, 0, sizeof(struct NestedData)); // Initialize to zeros

    // Pre-allocate memory for char* description in the decoded struct
    decoded_nested.description = (char*)malloc(256);
    REQUIRE(decoded_nested.description != nullptr); // Ensure allocation succeeded

    CborParser nested_parser;
    CborValue nested_it;
    CborError err = cbor_parser_init(nested_buffer, nested_encoded_len, 0, &nested_parser, &nested_it);
    CHECK_EQ(err, CborNoError);

    CHECK(decode_NestedData(&decoded_nested, &nested_it));
    MESSAGE("NestedData decoded successfully.");

    // Assertions for nested data
    CHECK_EQ(decoded_nested.inner_data.id, original_nested.inner_data.id);
    CHECK_EQ(strcmp(decoded_nested.inner_data.name, original_nested.inner_data.name), 0);
    CHECK_EQ(decoded_nested.inner_data.is_active, original_nested.inner_data.is_active);
    CHECK_EQ(decoded_nested.inner_data.temperature, doctest::Approx(original_nested.inner_data.temperature));
    CHECK_EQ(memcmp(decoded_nested.inner_data.flags, original_nested.inner_data.flags, sizeof(original_nested.inner_data.flags)), 0);
    CHECK_EQ(strcmp(decoded_nested.description, original_nested.description), 0);
    CHECK_EQ(decoded_nested.value, original_nested.value);

    // Clean up allocated memory
    free(original_nested.description);
    free(decoded_nested.description);
}
