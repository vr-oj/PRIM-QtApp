cmake_minimum_required(VERSION 3.14)
project(cambridge)

set(CMAKE_CXX_STANDARD 17)

# Set paths manually if needed
set(IC4_DIR "C:/Program Files/The Imaging Source Europe GmbH/IC Imaging Control 4/sdk/cpp")  # <-- Adjust this if different
set(PYBIND11_DIR "")

# Find Python and pybind11
find_package(Python3 REQUIRED COMPONENTS Interpreter Development)
find_package(pybind11 REQUIRED)

# Include IC4 SDK
include_directories(${IC4_DIR}/include)
link_directories(${IC4_DIR}/lib/x64)  # You might need to use /lib/win64 depending on SDK

# Create the Python extension module
add_library(cambridge MODULE CameraManager.cpp bindings.cpp)

# Link libraries
target_link_libraries(cambridge PRIVATE pybind11::module ICImagingControl)

# Output as cambridge.pyd on Windows
set_target_properties(cambridge PROPERTIES PREFIX "" SUFFIX ".pyd")
