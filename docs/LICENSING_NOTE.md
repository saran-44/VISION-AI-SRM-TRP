# Licensing & Compliance Note: Ultralytics AGPL-3.0

## Context & Executive Summary
The core vehicle and sticker detection pipeline uses **Ultralytics YOLO** (`ultralytics` Python package and `.pt` model weights). Ultralytics is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.

- **Internal University Deployment (On-Premise)**: Using this software internally across SRM TRP campus gates for educational and administrative transport monitoring is standard internal operational use.
- **External Commercial Distribution**: If this software, its binary (`VisionAI.exe` / `VisionAI-Setup.exe`), or hosted cloud services are distributed or sold commercially to third-party institutions, organizations, or clients, the AGPL-3.0 copyleft requirements are triggered.

---

## Two Commercial Compliance Paths

Prior to selling, SaaS-hosting for third parties, or distributing binaries externally, the product owner must select one of the following two paths:

### Path A: Commercial Enterprise License (Ultralytics)
- **Mechanism**: Purchase a proprietary commercial license directly from Ultralytics LLC.
- **Advantage**: Allows the application and its proprietary gate management / fleet database code to remain closed-source and proprietary. No requirement to disclose source code under AGPL-3.0.
- **Action**: Contact `licensing@ultralytics.com` to obtain an Enterprise Commercial License covering deployment on customer PCs or cloud nodes.

### Path B: Permissive Open-Source Detector Migration (Clean-Room / Apache 2.0)
- **Mechanism**: Replace the `ultralytics` inference runtime with an Apache-2.0 or MIT-licensed detector engine.
- **Options**:
  1. **ONNX Runtime Engine**: Export the weights to ONNX format and run inference via Microsoft's `onnxruntime` (MIT License) with custom non-maximum suppression (NMS) and decoding.
  2. **YOLO-World / RT-DETR / OpenCV DNN**: Use Apache 2.0-licensed models or OpenCV's native DNN inference module without linking against Ultralytics GPL code.
  3. **Architectural Isolation**: Place the detector inside a separate, decoupled microservice/container with a clean REST/gRPC boundary, keeping the transport management system completely decoupled.
- **Advantage**: Zero license fees, no copyleft obligations, full commercial freedom for the transport portal product.

---

## Model Weights & Dataset Provenance
The model weights (`best.pt`, `anpr_best.pt`, and `weights/vehicle.pt`) were trained specifically on local campus vehicle and gate footage. Before external distribution, verify that any training data containing third-party vehicle registrations or faces conforms with institutional privacy guidelines (see `docs/PRIVACY.md`).
