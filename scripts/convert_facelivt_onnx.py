"""
Script to convert FaceLiVT PyTorch model (.pt) to ONNX (.onnx).
Run this script to generate the ONNX model required by the OpenCV DNN pipeline.
"""
import torch
import cv2
import numpy as np
import sys
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))  # Allow importing from models/

MODEL_PATH_PT = BASE_DIR / "models" / "facelivtv2_s.pt"
MODEL_PATH_ONNX = BASE_DIR / "models" / "facelivtv2_s_512.onnx"

from models.facelivtv2 import facelivtv2_s, reparameterize

def main():
    if not MODEL_PATH_PT.exists():
        print(f"[-] Error: PyTorch model not found at {MODEL_PATH_PT}")
        return

    print(f"[*] Loading PyTorch model from {MODEL_PATH_PT}...")
    
    try:
        # Create the model architecture
        model = facelivtv2_s(num_classes=512)
        
        # Load the weights (state_dict)
        state_dict = torch.load(str(MODEL_PATH_PT), map_location="cpu")
        
        # Sometimes weights are saved under a 'state_dict' key if it's a checkpoint
        if 'state_dict' in state_dict:
            state_dict = state_dict['state_dict']
            
        model.load_state_dict(state_dict, strict=False)
        print("[+] Weights loaded successfully.")
        
        # Reparameterize for deployment (fuses BN into Conv, removes branches)
        print("[*] Reparameterizing model for inference...")
        model = reparameterize(model)
        
    except Exception as e:
        print("[-] Failed to load the model.")
        print("    Error:", e)
        return

    model.eval()

    # FaceLiVT expects 112x112 input
    dummy_input = torch.randn(1, 3, 112, 112, device="cpu")

    print(f"[*] Exporting to ONNX: {MODEL_PATH_ONNX} ...")
    try:
        # We don't use dynamic_axes anymore as Dynamo export in recent PyTorch doesn't recommend it,
        # and OpenCV DNN usually works fine with static batch size for face recognition embeddings.
        torch.onnx.export(
            model, 
            dummy_input, 
            str(MODEL_PATH_ONNX),
            export_params=True,
            opset_version=18,  # PyTorch >= 2.x yêu cầu tối thiểu opset 18
            do_constant_folding=True,
            input_names=['input'],
            output_names=['output']
        )
        print("[+] Successfully exported to ONNX!")
    except Exception as e:
        print("[-] Export failed:", e)
        return

    # Verify with OpenCV DNN
    print("[*] Verifying ONNX model with OpenCV DNN...")
    try:
        # Load via numpy buffer to avoid OpenCV Windows Unicode path issues
        buf = np.fromfile(str(MODEL_PATH_ONNX), dtype=np.uint8)
        net = cv2.dnn.readNetFromONNX(buf.tobytes())
        blob = np.random.randn(1, 3, 112, 112).astype(np.float32)
        net.setInput(blob)
        out = net.forward()
        print(f"[+] OpenCV DNN verification passed! Output shape: {out.shape}")
        if out.shape[1] != 512:
            print(f"[!] Warning: Expected 512-dim output, but got {out.shape[1]}")
    except Exception as e:
        print("[-] OpenCV DNN verification failed:", e)

if __name__ == "__main__":
    main()
