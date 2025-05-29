cmake_minimum_required(VERSION 3.14)
project(cambridge)

set(CMAKE_CXX_STANDARD 17)

# IC4 SDK setup
set(IC4_DIR "C:/Program Files/The Imaging Source Europe GmbH/ic4")
include_directories("C:/Program Files/The Imaging Source Europe GmbH/ic4/include/tisic4")
link_directories("${IC4_DIR}/lib/x64")

# Python + pybind11 (now system-wide)
find_package(Python3 REQUIRED COMPONENTS Interpreter Development)

# Python headers and pybind11
include_directories("C:/Program Files/Python313/include")
link_directories("C:/Program Files/Python313/libs")
include_directories("C:/Program Files/Python313/Lib/site-packages/pybind11/include")

# Create the Python extension module
add_library(cambridge MODULE CameraManager.cpp bindings.cpp)

# Link with IC Imaging Control library
target_link_libraries(cambridge PRIVATE ICImagingControl)

# Output file format (.pyd on Windows)
set_target_properties(cambridge PROPERTIES PREFIX "" SUFFIX ".pyd")
