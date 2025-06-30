# TODO / Future Enhancements

We're continuously working to improve `Ailuropoda`. Here are some planned features:

*   **CBOR to JSON / JSON to CBOR Helpers**: Implement optional C helper functions for converting between CBOR and JSON, simplifying debugging and interoperability.
*   **Dynamic Memory Management for Pointers**: Enhance `char*` and other pointer decoding to optionally handle dynamic memory allocation (`malloc`/`free`) for decoded data, reducing the burden on the user.
*   **Union Type Support**: Add support for C `union` types.
*   **Enum Type Support**: Generate appropriate CBOR representations for C `enum` types.
*   **Improved Error Handling**: Provide more granular error codes and messages in the generated C functions.
*   **Advanced Array Support**: Explore support for multi-dimensional arrays and flexible array members.
