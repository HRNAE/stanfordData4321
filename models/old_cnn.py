import os
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.cuda.amp import GradScaler, autocast
import torchvision.transforms as transforms
from torch.utils.data import DataLoader, Dataset, random_split
from torchvision.utils import save_image
from PIL import Image
import pandas as pd
import logging
import optuna
import numpy as np
import matplotlib.pyplot as plt

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Use GPU if available
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
logging.info("Using device: %s", device)

# Load the Excel file
excel_file_path = './dataRef/release_midas.xlsx'
if not os.path.exists(excel_file_path):
    raise FileNotFoundError(f"{excel_file_path} does not exist. Please check the path.")

df = pd.read_excel(excel_file_path)
logging.info("Excel file loaded. First few rows:")
logging.info("%s", df.head())

# Define categories and image size
categories = ['7-malignant-bcc', '1-benign-melanocytic nevus', '6-benign-other',
              '14-other-non-neoplastic/inflammatory/infectious', '8-malignant-scc',
              '9-malignant-sccis', '10-malignant-ak', '3-benign-fibrous papule',
              '4-benign-dermatofibroma', '2-benign-seborrheic keratosis',
              '5-benign-hemangioma', '11-malignant-melanoma',
              '13-other-melanocytic lesion with possible re-excision (severe/spitz nevus, aimp)',
              '12-malignant-other']
img_size = 224  # Image size set to 224

# Compose the transformation pipeline
transform = transforms.Compose([
    transforms.Resize((img_size, img_size)),
    transforms.ToTensor(),
    transforms.Normalize((0.5,), (0.5,))
])

# Define the augmentation pipeline
augmentation_transforms = transforms.Compose([
    transforms.RandomResizedCrop(img_size),
    transforms.RandomHorizontalFlip(),
    transforms.RandomVerticalFlip(),
    transforms.RandomRotation(10),
    transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2, hue=0.2)
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
                        logging.warning("Label '%s' not in label_map.", label)
                        continue
                    valid_paths.append((img_name, label))
                    img_found = True
                    break
            if not img_found:
                logging.warning("Image %s not found in any root directory.", row['midas_file_name'])
        logging.info("Total valid paths found: %d", len(valid_paths))
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
    os.path.join(os.getcwd(), '/root/stanfordData4321/stanfordData4321/standardized_images/images1'),
    os.path.join('/root/stanfordData4321/stanfordData4321/standardized_images/images2'),
    os.path.join('/root/stanfordData4321/stanfordData4321/standardized_images/images3'),
    os.path.join('/root/stanfordData4321/stanfordData4321/standardized_images/images4')
]

# Save augmented images
def save_augmented_images(dataset, output_dir, num_augmentations=5):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    total_images = len(dataset)
    interval = max(total_images // 10, 1)

    logging.info("Starting to save augmented images...")
    for idx in range(total_images):
        if idx % interval == 0:
            logging.info("Processing image %d/%d", idx, total_images)
        
        img, label = dataset[idx]
        label_dir = os.path.join(output_dir, str(label.item()))
        if not os.path.exists(label_dir):
            os.makedirs(label_dir)
        
        original_img_path = os.path.join(label_dir, f"{idx}_original.png")
        save_image(img, original_img_path)
        
        pil_img = transforms.ToPILImage()(img)
        for aug_idx in range(num_augmentations):
            augmented_img = augmentation_transforms(pil_img)
            augmented_img = transform(augmented_img)
            augmented_img_path = os.path.join(label_dir, f"{idx}_aug_{aug_idx}.png")
            save_image(augmented_img, augmented_img_path)
    
    logging.info("Finished saving augmented images.")

# Create dataset and save augmented images
dataset = ExcelImageDataset(excel_file_path, root_dirs, transform)
logging.info("Dataset length before augmentation: %d", len(dataset))

output_dir = './augmented_images2'
save_augmented_images(dataset, output_dir, num_augmentations=5)

# Define the combined dataset class
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
        return len(self.original_dataset) + len(self.augmented_paths)

    def __getitem__(self, idx):
        if idx < len(self.original_dataset):
            return self.original_dataset[idx]
        else:
            img_path, label = self.augmented_paths[idx - len(self.original_dataset)]
            image = Image.open(img_path).convert("RGB")
            if self.transform:
                image = self.transform(image)
            return image, torch.tensor(label, dtype=torch.long)

# Create the combined dataset
logging.info("Creating combined dataset...")
augmented_dataset = AugmentedImageDataset(dataset, output_dir, transform)
logging.info("Total images in augmented dataset: %d", len(augmented_dataset))

# Split dataset into training and testing subsets
logging.info("Splitting dataset into training and testing subsets...")
train_size = int(0.8 * len(augmented_dataset))
test_size = len(augmented_dataset) - train_size
train_dataset, test_dataset = random_split(augmented_dataset, [train_size, test_size])

logging.info("Length train dataset: %d", len(train_dataset))
logging.info("Length test dataset: %d", len(test_dataset))

# Define the custom model class based on your initial architecture
class CustomModel(nn.Module):
    def __init__(self):
        super(CustomModel, self).__init__()
        self.conv1 = nn.Conv2d(in_channels=3, out_channels=8, kernel_size=3, padding=1)
        self.pool1 = nn.MaxPool2d(kernel_size=2, stride=2, padding=0)
        self.conv2 = nn.Conv2d(in_channels=8, out_channels=16, kernel_size=3, padding=1)
        self.pool2 = nn.MaxPool2d(kernel_size=2, stride=2, padding=0)
        self.conv3 = nn.Conv2d(in_channels=16, out_channels=32, kernel_size=3, padding=1)
        self.pool3 = nn.MaxPool2d(kernel_size=2, stride=2, padding=0)
        self.conv4 = nn.Conv2d(in_channels=32, out_channels=64, kernel_size=3, padding=1)
        self.pool4 = nn.MaxPool2d(kernel_size=2, stride=2, padding=0)
        self.conv5 = nn.Conv2d(in_channels=64, out_channels=128, kernel_size=3, padding=1)
        self.pool5 = nn.MaxPool2d(kernel_size=2, stride=2, padding=0)
        self.fc1 = nn.Linear(128 * 7 * 7, 512)
        self.fc2 = nn.Linear(512, 128)
        self.fc3 = nn.Linear(128, len(categories))

    def forward(self, x):
        x = self.pool1(F.relu(self.conv1(x)))
        x = self.pool2(F.relu(self.conv2(x)))
        x = self.pool3(F.relu(self.conv3(x)))
        x = self.pool4(F.relu(self.conv4(x)))
        x = self.pool5(F.relu(self.conv5(x)))
        x = x.view(-1, 128 * 7 * 7)
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        x = self.fc3(x)
        return x

# Create model instance, loss function, and optimizer
model = CustomModel().to(device)
criterion = nn.CrossEntropyLoss()
optimizer = optim.SGD(model.parameters(), lr=0.001, momentum=0.9)

# Set up data loaders
batch_size = 16
train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, num_workers=4)
test_loader = DataLoader(test_dataset, batch_size=batch_size, shuffle=False, num_workers=4)

# Train the model
def train_model(model, train_loader, criterion, optimizer, num_epochs=25):
    model.train()
    for epoch in range(num_epochs):
        running_loss = 0.0
        for i, (images, labels) in enumerate(train_loader):
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            running_loss += loss.item()
        logging.info("Epoch [%d/%d], Loss: %.4f", epoch+1, num_epochs, running_loss/len(train_loader))

logging.info("Starting training...")
train_model(model, train_loader, criterion, optimizer, num_epochs=25)

# Test the model
def test_model(model, test_loader):
    model.eval()
    correct = 0
    total = 0
    with torch.no_grad():
        for images, labels in test_loader:
            images, labels = images.to(device), labels.to(device)
            outputs = model(images)
            _, predicted = torch.max(outputs.data, 1)
            total += labels.size(0)
            correct += (predicted == labels).sum().item()
    logging.info('Test Accuracy: %.2f %%', 100 * correct / total)

logging.info("Starting testing...")
test_model(model, test_loader)

# Occlusion Sensitivity Helper Functions
def compute_occlusion_sensitivity(model, image, label, occlusion_size=16, occlusion_stride=8):
    model.eval()  # Set the model to evaluation mode
    image = image.unsqueeze(0)
    with torch.no_grad():
        original_output = model(image.to(device))
        original_score = F.softmax(original_output, dim=1)[0, label].item()

    sensitivity_map = np.zeros((image.size(2), image.size(3)))

    for y in range(0, image.size(2), occlusion_stride):
        for x in range(0, image.size(3), occlusion_stride):
            occluded_image = image.clone()
            occluded_image[:, :, y:y+occlusion_size, x:x+occlusion_size] = 0.0
            with torch.no_grad():
                output = model(occluded_image.to(device))
                score = F.softmax(output, dim=1)[0, label].item()
            sensitivity_map[y:y+occlusion_size, x:x+occlusion_size] = original_score - score

    return sensitivity_map

def plot_occlusion_sensitivity(sensitivity_map, original_image, save_path=None):
    original_image_np = np.transpose(original_image.numpy(), (1, 2, 0))
    plt.figure(figsize=(10, 5))
    plt.subplot(1, 2, 1)
    plt.imshow((original_image_np * 0.5) + 0.5)
    plt.title('Original Image')
    plt.subplot(1, 2, 2)
    plt.imshow(sensitivity_map, cmap='hot', interpolation='nearest')
    plt.colorbar()
    plt.title('Occlusion Sensitivity')
    if save_path:
        plt.savefig(save_path)
    plt.show()

# Pick an image from the test dataset and compute occlusion sensitivity
test_img, test_label = test_dataset[0]
test_img = test_img.to(device)
test_label = test_label.to(device)
sensitivity_map = compute_occlusion_sensitivity(model, test_img, test_label.item(), occlusion_size=16, occlusion_stride=8)
plot_occlusion_sensitivity(sensitivity_map, test_img.cpu(), save_path='./occlusion_sensitivity.png')
