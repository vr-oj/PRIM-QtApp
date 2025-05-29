cmake_minimum_required(VERSION 3.14)
project(cambridge)

set(CMAKE_CXX_STANDARD 17)

set(IC4_DIR "C:/Program Files/The Imaging Source Europe GmbH/ic4")
include_directories(${IC4_DIR}/include)
link_directories(${IC4_DIR}/lib/x64)

# Python and pybind11
find_package(Python3 REQUIRED COMPONENTS Interpreter Development)
include_directories(${pybind11_INCLUDE_DIR})

add_library(cambridge MODULE CameraManager.cpp bindings.cpp)
target_link_libraries(cambridge PRIVATE pybind11::module ICImagingControl)
set_target_properties(cambridge PROPERTIES PREFIX "" SUFFIX ".pyd")
