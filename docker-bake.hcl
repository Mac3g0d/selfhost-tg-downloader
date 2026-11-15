# One BuildKit invocation builds every image the pipeline needs, sharing the
# common stages. CI adds cache and archive outputs on top of this file.
variable "APK_REFRESH" {
  default = ""
}

group "default" {
  targets = ["ci", "runtime", "scan"]
}

target "_common" {
  context    = "."
  dockerfile = "Dockerfile"
  args = {
    APK_REFRESH = APK_REFRESH
  }
}

target "ci" {
  inherits = ["_common"]
  target   = "ci"
  tags     = ["downloader-ci:checked"]
}

target "runtime" {
  inherits = ["_common"]
  target   = "runtime"
  tags     = ["downloader-runtime:checked"]
}

target "scan" {
  inherits = ["_common"]
  target   = "scan"
  tags     = ["downloader-scan:checked"]
}
