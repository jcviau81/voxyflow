import onnxruntime as ort
import numpy as np

# Load models
mel_session = ort.InferenceSession('frontend/public/models/melspectrogram.onnx')

# Test with correct shape
audio = np.random.randn(1, 1280).astype(np.float32)  # Add batch dimension
mel_out = mel_session.run(None, {'input': audio})
print(f'Mel output shape: {mel_out[0].shape}')
print(f'Mel frames: {mel_out[0].shape[0]}, features per frame: {mel_out[0].shape[3]}')

# Now test embedding model with correct input
emb_session = ort.InferenceSession('frontend/public/models/embedding_model.onnx')
# Take 76 frames from mel output
mel_frames = mel_out[0][:76, :, :, :]  # shape: [76, 1, X, 32]
# Reshape to what embedding expects: [1, 76, 32, 1]
emb_input = mel_frames[:, 0, 0, :].reshape(1, 76, 32, 1)
print(f'\nEmbedding input shape: {emb_input.shape}')
emb_out = emb_session.run(None, {'input_1': emb_input})
print(f'Embedding output shape: {emb_out[0].shape}')
print(f'Embedding features: {emb_out[0].shape[3]}')
