cmake_minimum_required(VERSION 3.14)
project(cambridge)

set(CMAKE_CXX_STANDARD 17)

set(IC4_DIR "C:/Program Files/The Imaging Source Europe GmbH/ic4")
include_directories(${IC4_DIR}/include)
link_directories(${IC4_DIR}/lib/x64)

# Python and pybind11
find_package(Python3 REQUIRED COMPONENTS Interpreter Development)
include_directories("C:/Users/Tykocki Lab - PRIM/Documents/GitHub/PRIM-QtApp/.primenv/Lib/site-packages/pybind11/include")

add_library(cambridge MODULE CameraManager.cpp bindings.cpp)

# 🔥 REMOVE pybind11::module here 🔥
target_link_libraries(cambridge PRIVATE ICImagingControl)

set_target_properties(cambridge PROPERTIES PREFIX "" SUFFIX ".pyd")
