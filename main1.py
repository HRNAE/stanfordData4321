#with data augmentation resnet model
import os
import torch
import torch.nn as nn
import torch.optim as optim
import torchvision.transforms as transforms
import torchvision.models as models
from torch.utils.data import DataLoader, Dataset, random_split
from torchvision.utils import save_image
from PIL import Image
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pytorch_grad_cam import GradCAM
from pytorch_grad_cam.utils.image import show_cam_on_image
from collections import Counter
import random

# Print the current working directory
print("Current working directory:", os.getcwd())

# Load the Excel file
excel_file_path = './dataRef/release_midas.xlsx'
if not os.path.exists(excel_file_path):
    raise FileNotFoundError(f"{excel_file_path} does not exist. Please check the path.")

df = pd.read_excel(excel_file_path)
print("Excel file loaded. First few rows:")
print(df.head())

# Define categories and image size
categories = ['7-malignant-bcc', '1-benign-melanocytic nevus', '6-benign-other',
              '14-other-non-neoplastic/inflammatory/infectious', '8-malignant-scc',
              '9-malignant-sccis', '10-malignant-ak', '3-benign-fibrous papule',
              '4-benign-dermatofibroma', '2-benign-seborrheic keratosis',
              '5-benign-hemangioma', '11-malignant-melanoma',
              '13-other-melanocytic lesion with possible re-excision (severe/spitz nevus, aimp)',
              '12-malignant-other']
img_size = 224

# Compose the transformation pipeline
transform = transforms.Compose([
    transforms.Resize((img_size, img_size)),
    transforms.ToTensor(),
])

# Define the augmentation and processing pipeline
augmentation_transforms = transforms.Compose([
    transforms.RandomRotation(degrees=90, expand=False),  # Rotate the image without expanding
    transforms.Resize((224, 224)),  # Ensure consistency in size after rotation
    transforms.Pad(padding=(0, 0, 0, 0), fill=(255, 255, 255), padding_mode='constant')  # Pad to 700x700 with white background if necessary
])

# Convert image to tensor and normalize (this should be done separately)
to_tensor_and_normalize = transforms.Compose([
    transforms.ToTensor(),  # Convert to tensor
    transforms.Normalize((0.5,0.5,0.5),(0.5,0.5,0.5))  # Normalize
])

# Function to save augmented images with correct dimensions
# def save_augmented_images_with_exact_cap(dataset, output_dir, target_count=1500):
#     if not os.path.exists(output_dir):
#         os.makedirs(output_dir)
#    
#     label_counts = Counter(label.item() for _, label in dataset)
    
#     for idx in range(len(dataset)):
#         img, label = dataset[idx]
#         label_dir = os.path.join(output_dir, str(label.item()))
#         if not os.path.exists(label_dir):
#             os.makedirs(label_dir)
        
#         # Count the number of images already saved for this label
#         current_count = len([f for f in os.listdir(label_dir) if f.endswith('.png')])
        
#         # If the current count is already at or above the target, skip further augmentation
#         if current_count >= target_count:
#             continue
        
#         # Save the original image if not yet saved
#         if current_count == 0:
#             original_img_path = os.path.join(label_dir, f"{idx}_original.png")
#             save_image(img, original_img_path)
#             current_count += 1
        
#         # Generate and save augmented images until the count reaches the target
#         pil_img = transforms.ToPILImage()(img)  # Convert tensor to PIL Image
#         while current_count < target_count:
#             augmented_img = augmentation_transforms(pil_img)  # Apply augmentation
#             augmented_img = to_tensor_and_normalize(augmented_img)  # Convert to tensor and normalize
#             augmented_img_path = os.path.join(label_dir, f"{idx}_aug_{current_count}.png")
#             save_image(augmented_img, augmented_img_path)
#             current_count += 1
#    
#     # Cap all labels at target_count by randomly selecting 1500 images if a label has more
#     for label in os.listdir(output_dir):
#         label_dir = os.path.join(output_dir, label)
#         images = [f for f in os.listdir(label_dir) if f.endswith('.png')]
#         if len(images) > target_count:
#             images_to_keep = random.sample(images, target_count)
#             images_to_remove = set(images) - set(images_to_keep)
#             for img in images_to_remove:
#                 os.remove(os.path.join(label_dir, img))

def imshow(img):
    img = img / 2 + 0.5
    npimg = img.cpu().numpy()  # Ensure tensor is moved to CPU
    plt.imshow(np.transpose(npimg, (1, 2, 0)))
    plt.show()

class ExcelImageDataset(Dataset):
    def __init__(self, excel_file, root_dirs, transform=None):
        self.data_frame = pd.read_excel(excel_file)
        self.data_frame.iloc[:, 0] = self.data_frame.iloc[:, 0].astype(str)
        self.root_dirs = root_dirs
        self.transform = transform

        # Ensure the label categories are consistent with the provided categories
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

        # Convert label to tensor with encoding
        label = torch.tensor(self.label_map.get(label, -1), dtype=torch.long)
        return image, label

# Define the root directories
root_dirs = [
    os.path.join(os.getcwd(), '/root/stanfordData4321/stanfordData4321/standardized_images/images1'),
    os.path.join('/root/stanfordData4321/stanfordData4321/standardized_images/images2'),
    os.path.join('/root/stanfordData4321/stanfordData4321/standardized_images/images3'),
    os.path.join('/root/stanfordData4321/stanfordData4321/standardized_images/images4')
]

# Function to count images per label
def count_images_per_label(dataset):
    label_counts = Counter(label.item() for _, label in dataset)
    return {categories[label]: count for label, count in label_counts.items()}

# Count images before augmentation
dataset = ExcelImageDataset(excel_file_path, root_dirs, transform)
pre_augmentation_counts = count_images_per_label(dataset)
print("Image counts before augmentation:")
for label, count in pre_augmentation_counts.items():
    print(f"{label}: {count}")


#Save augmented images (PROBLEM AREA FOR AUGMENTATION)
def save_augmented_images_with_exact_cap(dataset, output_dir, target_count=4):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    
    label_to_images = {}
    for idx in range(len(dataset)):
        img, label = dataset[idx]
        label = label.item()
        if label not in label_to_images:
            label_to_images[label] = []
        label_to_images[label].append((img, idx))

    # For each label, save images until the folder has 1500 images
    for label, images in label_to_images.items():
        label_dir = os.path.join(output_dir, str(label))

        if not os.path.exists(label_dir):
            os.makedirs(label_dir)

        # Count the number of images already saved for this label
        current_count = len([f for f in os.listdir(label_dir) if f.endswith('.png')])

        # First, save all the original images
        while current_count < target_count:
            for img, idx in images:
                # Stop if we've already hit the target count
                if current_count >= target_count:
                    break

                pil_img = transforms.ToPILImage()(img)
                
                
                augmented_img = augmentation_transforms(pil_img) if current_count >= len(images) else pil_img
                augmented_img_tensor = transform(augmented_img)  # Convert back to tensor

                # Save 
                augmented_img_path = os.path.join(label_dir, f"{idx}_aug_{current_count}.png")
                save_image(augmented_img_tensor, augmented_img_path)
                
                current_count += 1


# Create dataset and save augmented images
output_dir = './augmented_images2'
save_augmented_images_with_exact_cap(dataset, output_dir, target_count=1500)

# Function to count images per label in augmented dataset
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

# Create the combined dataset
augmented_dataset = AugmentedImageDataset(dataset, output_dir, transform)
print(f"Total images in augmented dataset: {len(augmented_dataset)}")

# Count images after augmentation
post_augmentation_counts = count_images_per_label(augmented_dataset)
print("Image counts after augmentation:")
for label, count in post_augmentation_counts.items():
    print(f"{label}: {count}")

# # Split dataset
# train_size = int(0.8 * len(augmented_dataset))
# test_size = len(augmented_dataset) - train_size
# train_dataset, test_dataset = random_split(augmented_dataset, [train_size, test_size])

# print(f"Train dataset length: {len(train_dataset)}, Test dataset length: {len(test_dataset)}")

# train_loader = DataLoader(train_dataset, batch_size=4, shuffle=True)
# test_loader = DataLoader(test_dataset, batch_size=4, shuffle=False)

# # Load pre-trained model and modify the final layer
# weights = models.ResNet18_Weights.DEFAULT
# net = models.resnet18(weights=weights)
# num_ftrs = net.fc.in_features
# net.fc = nn.Linear(num_ftrs, len(categories))

# # Move the model to GPU
# device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
# net.to(device)
# print(device)

# # Define loss function and optimizer
# criterion = nn.CrossEntropyLoss()
# optimizer = optim.SGD(net.parameters(), lr=0.1, momentum=0.9)

# # Training loop
# for epoch in range(1):  # Loop over the dataset multiple times
#     running_loss = 0.0
#     print(epoch)
#     for i, data in enumerate(train_loader, 0):
#         inputs, labels = data
#         inputs, labels = inputs.to(device), labels.to(device)

#         optimizer.zero_grad()
#         outputs = net(inputs)
#         loss = criterion(outputs, labels)
#         loss.backward()
#         optimizer.step()

#         running_loss += loss.item()
#         if i % 100 == 99:  # Print every 100 mini-batches
#             print(f'[{epoch + 1}, {i + 1}] loss: {running_loss / 100:.3f}')
#             running_loss = 0.0

# print('Finished Training')

# # Evaluate the model
# correct = 0
# total = 0
# with torch.no_grad():
#     for data in test_loader:
#         images, labels = data
#         outputs = net(images.to(device))
#         _, predicted = torch.max(outputs.data, 1)
#         total += labels.size(0)
#         correct += (predicted.cpu() == labels).sum().item()

# print(f'Accuracy of the network on the test images: {100 * correct // total} %')

# # Grad-CAM
# def apply_grad_cam(img_path, model, transform, target_layer):
#     model.eval()
#     image = Image.open(img_path).convert("RGB")
#     input_tensor = transform(image).unsqueeze(0).to(device)

#     with torch.no_grad():
#         output = model(input_tensor)
#         pred = output.argmax(dim=1)

#     grad_cam = GradCAM(model=model, target_layers=[target_layer], use_cuda=True)
#     grayscale_cam = grad_cam(input_tensor=input_tensor, target_category=pred.item())[0, :]
#     cam_image = show_cam_on_image(np.array(image), grayscale_cam, use_rgb=True)

#     plt.imshow(cam_image)
#     plt.show()

# # Example usage of Grad-CAM
# apply_grad_cam('./augmented_images/7-malignant-bcc/0_original.png', net, net.layer4[1].conv2, transform)

# # Save model checkpoint
# checkpoint_path = './model_checkpoint.pth'
# torch.save(net.state_dict(), checkpoint_path)
# print(f"Model checkpoint saved to {checkpoint_path}")
