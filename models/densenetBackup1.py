import os
import torch
import torch.nn as nn
import torch.optim as optim
import torchvision.transforms as transforms
from torch.utils.data import DataLoader, Dataset
from PIL import Image
import pandas as pd
from collections import Counter
import optuna
import matplotlib.pyplot as plt
import cv2
import numpy as np
import matplotlib.cm as cm
import torchvision.models as models
from torchvision.models import densenet201, DenseNet201_Weights

# Define categories and image size
categories = ['7-malignant-bcc', '1-benign-melanocytic nevus', '6-benign-other',
              '14-other-non-neoplastic/inflammatory/infectious', '8-malignant-scc',
              '9-malignant-sccis', '10-malignant-ak', '3-benign-fibrous papule',
              '4-benign-dermatofibroma', '2-benign-seborrheic keratosis',
              '5-benign-hemangioma', '11-malignant-melanoma',
              '13-other-melanocytic lesion with possible re-excision (severe/spitz nevus, aimp)',
              '12-malignant-other']
img_size = 224

# Define transformations
transform = transforms.Compose([
    transforms.Resize((img_size, img_size)),
    transforms.ToTensor(),
])

class ExcelImageDataset(Dataset):
    def __init__(self, excel_file, root_dirs, transform=None):
        self.data_frame = pd.read_excel(excel_file)
        self.data_frame.iloc[:, 0] = self.data_frame.iloc[:, 0].astype(str)
        self.root_dirs = root_dirs
        self.transform = transform
        self.label_map = {label: idx for idx, label in enumerate(categories)}
        self.image_paths = self._get_image_paths()

    def _get_image_paths(self):
        valid_paths = []
        for idx, row in self.data_frame.iterrows():
            img_found = False
            for root_dir in self.root_dirs:
                img_name = os.path.join(root_dir, row['midas_file_name'])
                if os.path.isfile(img_name):
                    label = row['clinical_impression_1']
                    if label not in self.label_map:
                        print(f"Warning: Label '{label}' not in label_map.")
                        continue
                    valid_paths.append((img_name, label))
                    img_found = True
                    break
            if not img_found:
                print(f"Warning: Image {row['midas_file_name']} not found in any root directory.")
        print(f"Total valid paths found: {len(valid_paths)}")
        return valid_paths

    def __len__(self):
        return len(self.image_paths)

    def __getitem__(self, idx):
        img_name, label = self.image_paths[idx]
        image = Image.open(img_name).convert("RGB")
        if self.transform:
            image = self.transform(image)
        label = torch.tensor(self.label_map.get(label, -1), dtype=torch.long)
        return image, label

# Define the root directories
root_dirs = [
    '/root/stanfordData4321/standardized_images/images1',
    '/root/stanfordData4321/standardized_images/images2',
    '/root/stanfordData4321/standardized_images/images3',
    '/root/stanfordData4321/standardized_images/images4'
]

# Augmented dataset class
class AugmentedImageDataset(Dataset):
    def __init__(self, original_dataset, augmented_dir, transform=None):
        self.original_dataset = original_dataset
        self.augmented_dir = augmented_dir
        self.transform = transform
        self.augmented_paths = self._get_augmented_paths()

    def _get_augmented_paths(self):
        augmented_paths = []
        for root, _, files in os.walk(self.augmented_dir):
            for file in files:
                if file.endswith(".png"):
                    img_path = os.path.join(root, file)
                    label = int(os.path.basename(root))
                    augmented_paths.append((img_path, label))
        return augmented_paths

    def __len__(self):
        return len(self.augmented_paths)

    def __getitem__(self, idx):
        img_path, label = self.augmented_paths[idx]
        image = Image.open(img_path).convert("RGB")
        if self.transform:
            image = self.transform(image)
        return image, torch.tensor(label, dtype=torch.long)

# Create augmented dataset
augmented_dataset = AugmentedImageDataset(ExcelImageDataset('./dataRef/release_midas.xlsx', root_dirs, transform), './augmented_images', transform)
print(f"Total images in augmented dataset: {len(augmented_dataset)}")

# Train and test split
train_size = int(0.8 * len(augmented_dataset))
test_size = len(augmented_dataset) - train_size
train_dataset, test_dataset = torch.utils.data.random_split(augmented_dataset, [train_size, test_size])

train_loader = DataLoader(train_dataset, batch_size=4, shuffle=True)
test_loader = DataLoader(test_dataset, batch_size=4, shuffle=False)

# Load pre-trained DenseNet model and modify final layer
weights = DenseNet201_Weights.DEFAULT
net = densenet201(weights=weights)
num_ftrs = net.classifier.in_features
net.classifier = nn.Linear(num_ftrs, len(categories))

# Move the model to GPU
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
net.to(device)
# Optuna optimization
def objective(trial):
    lr = trial.suggest_float('lr', 1e-5, 1e-1, log=True)
    momentum = trial.suggest_float('momentum', 0.5, 0.9)
    
    optimizer = optim.SGD(net.parameters(), lr=lr, momentum=momentum)
    criterion = nn.CrossEntropyLoss()

    for epoch in range(1):  # Fewer epochs for faster optimization
        net.train()
        running_loss = 0.0
        for inputs, labels in train_loader:
            inputs, labels = inputs.to(device), labels.to(device)

            optimizer.zero_grad()
            outputs = net(inputs)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            running_loss += loss.item()

    net.eval()
    correct = 0
    total = 0
    with torch.no_grad():
        for inputs, labels in test_loader:
            inputs, labels = inputs.to(device), labels.to(device)
            outputs = net(inputs)
            _, predicted = torch.max(outputs.data, 1)
            total += labels.size(0)
            correct += (predicted == labels).sum().item()
    
    accuracy = correct / total
    return accuracy

study = optuna.create_study(direction='maximize')
study.optimize(objective, n_trials=1)

best_params = study.best_params
print("Best parameters found by Optuna:", best_params)

# Training with the best parameters
best_lr = best_params['lr']
best_momentum = best_params['momentum']
optimizer = optim.SGD(net.parameters(), lr=best_lr, momentum=best_momentum)
criterion = nn.CrossEntropyLoss()

for epoch in range(5):  # Adjust epoch count
    net.train()
    running_loss = 0.0
    for i, data in enumerate(train_loader, 0):
        inputs, labels = data
        inputs, labels = inputs.to(device), labels.to(device)

        optimizer.zero_grad()
        outputs = net(inputs)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()

        running_loss += loss.item()
        if i % 2000 == 1999:
            print(f'[{epoch + 1}, {i + 1}] loss: {running_loss / 100:.3f}')
            running_loss = 0.0

print('Finished Training')

# Evaluate the model
net.eval()

all_preds = []
all_labels = []

# Iterate through the test set
with torch.no_grad():
    for images, labels in test_loader:
        images, labels = images.to(device), labels.to(device)
        
        # Get model predictions
        outputs = net(images)
        _, preds = torch.max(outputs, 1)
        
        # Collect predictions and labels
        all_preds.extend(preds.cpu().numpy())
        all_labels.extend(labels.cpu().numpy())

from sklearn.metrics import precision_score, recall_score, f1_score, accuracy_score

# Calculate precision, recall, f1 score, and accuracy
precision = precision_score(all_labels, all_preds, average='weighted')
recall = recall_score(all_labels, all_preds, average='weighted')
f1 = f1_score(all_labels, all_preds, average='weighted')
accuracy = accuracy_score(all_labels, all_preds)

print(f"Accuracy: {accuracy * 100:.2f}%")
print(f"Precision: {precision:.4f}")
print(f"Recall: {recall:.4f}")
print(f"F1 Score: {f1:.4f}")


def generate_occlusion_sensitivity_map(image, model, occlusion_size=15, occlusion_stride=15):
    """
    Generate an occlusion sensitivity map for the given image and model.

    Args:
        image (torch.Tensor): Input image tensor of shape (1, C, H, W).
        model (torch.nn.Module): Trained model.
        occlusion_size (int): Size of the occlusion window.
        occlusion_stride (int): Stride of the occlusion window.

    Returns:
        np.ndarray: Sensitivity map of the same size as the input image.
    """
    # Set model to evaluation mode
    model.eval()

    # Get original image size
    if len(image.size()) == 5:  # If it's a 5D tensor
        image = image.squeeze(1)  # Remove the extra dimension
    _, _, h, w = image.size()

    # Get the prediction for the original image
    with torch.no_grad():
        original_output = model(image)
    original_class = original_output.argmax(dim=1).item()

    # Initialize sensitivity map
    sensitivity_map = np.zeros((h, w))

    # Occlude part of the image and get model output for each occlusion
    for i in range(0, h, occlusion_stride):
        for j in range(0, w, occlusion_stride):
            # Create a copy of the original image
            occluded_image = image.clone()

            # Apply occlusion (e.g., zero out a region)
            occluded_image[:, :, i:i + occlusion_size, j:j + occlusion_size] = 0

            # Get model prediction for the occluded image
            with torch.no_grad():
                occluded_output = model(occluded_image)
            occluded_score = occluded_output[0, original_class].item()

            # Fill the sensitivity map with the difference in score
            sensitivity_map[i:i + occlusion_size, j:j + occlusion_size] = original_output[0, original_class].item() - occluded_score

    # Normalize the sensitivity map
    sensitivity_map = (sensitivity_map - np.min(sensitivity_map)) / (np.max(sensitivity_map) - np.min(sensitivity_map))
    sensitivity_map = (sensitivity_map * 255).astype(np.uint8)

    return sensitivity_map

import os
import shutil

# List of 28 file paths

output_dir = '/root/stanfordData4321/OSDES'
os.makedirs(output_dir, exist_ok=True)  # Create directory if it doesn't exist

# List of image paths and corresponding data
image_paths = [
    '/root/stanfordData4321/clusters/cluster_0/img_0_31.png',
    '/root/stanfordData4321/clusters/cluster_0/img_1_6.png',
    '/root/stanfordData4321/clusters/cluster_1/img_0_13.png',
    '/root/stanfordData4321/clusters/cluster_1/img_1_5.png',
    '/root/stanfordData4321/clusters/cluster_2/img_0_27.png',
    '/root/stanfordData4321/clusters/cluster_2/img_1_4.png',
    '/root/stanfordData4321/clusters/cluster_3/img_0_11.png',
    '/root/stanfordData4321/clusters/cluster_3/img_0_22.png',
    '/root/stanfordData4321/clusters/cluster_4/img_0_6.png',
    '/root/stanfordData4321/clusters/cluster_4/img_0_18.png',
    '/root/stanfordData4321/clusters/cluster_5/img_0_7.png',
    '/root/stanfordData4321/clusters/cluster_5/img_0_16.png',
    '/root/stanfordData4321/clusters/cluster_6/img_0_21.png',
    '/root/stanfordData4321/clusters/cluster_6/img_0_23.png',
    '/root/stanfordData4321/clusters/cluster_7/img_0_0.png',
    '/root/stanfordData4321/clusters/cluster_7/img_0_1.png',
    '/root/stanfordData4321/clusters/cluster_8/img_1_0.png',
    '/root/stanfordData4321/clusters/cluster_8/img_1_1.png',
    '/root/stanfordData4321/clusters/cluster_9/img_0_14.png',
    '/root/stanfordData4321/clusters/cluster_9/img_0_15.png',
    '/root/stanfordData4321/clusters/cluster_10/img_0_4.png',
    '/root/stanfordData4321/clusters/cluster_10/img_0_12.png',
    '/root/stanfordData4321/clusters/cluster_11/img_0_2.png',
    '/root/stanfordData4321/clusters/cluster_11/img_0_17.png',
    '/root/stanfordData4321/clusters/cluster_12/img_1_19.png',
    '/root/stanfordData4321/clusters/cluster_12/img_2_8.png',
    '/root/stanfordData4321/clusters/cluster_13/img_0_3.png',
    '/root/stanfordData4321/clusters/cluster_13/img_3_5.png',
]  # Replace with your list of image paths
# Assume you have a DataLoader or similar mechanism to load images and labels
for img_path in image_paths:
    # Load and preprocess the image
    try:
        image = Image.open(img_path).convert("RGB")
        image = transform(image).unsqueeze(0).to(device)

        # Generate the sensitivity map
        sensitivity_map = generate_occlusion_sensitivity_map(image, net)

        # Convert to NumPy array if necessary
        if isinstance(sensitivity_map, torch.Tensor):
            sensitivity_map = sensitivity_map.squeeze().cpu().numpy()

        # Resize and save the sensitivity map
        os.makedirs('./OSDES', exist_ok=True)
        result_path = os.path.join('./OS', os.path.basename(img_path).replace('.jpg', '_sensitivity.png'))
        cv2.imwrite(result_path, sensitivity_map)
        print(f"Sensitivity map saved for {img_path} at {result_path}")

    except Exception as e:
        print(f"Error processing {img_path}: {e}")

# GitHub commands to update repository
os.system("git add ./OS/*")
os.system("git commit -m 'Added updated sensitivity maps'")
os.system("git push")
