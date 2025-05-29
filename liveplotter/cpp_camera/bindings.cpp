// bindings.cpp
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>
#include "CameraManager.hpp"

namespace py = pybind11;

PYBIND11_MODULE(cambridge, m)
{
    py::class_<CameraManager>(m, "CameraManager")
        .def(py::init<>())
        .def("initialize", &CameraManager::initialize)
        .def("shutdown", &CameraManager::shutdown)
        .def("list_formats", &CameraManager::list_formats)
        .def("get_frame", [](CameraManager &self)
             {
            int w = 0, h = 0, c = 0;
            std::vector<uint8_t> data = self.get_frame(w, h, c);
            return py::array_t<uint8_t>({h, w, c}, data.data()); });
}