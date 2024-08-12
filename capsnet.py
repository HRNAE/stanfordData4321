import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms
from PIL import Image
import pandas as pd
import os

# Define custom dataset class to load images and corresponding labels from Excel and folder structure
class ExcelImageDataset(Dataset):
    def __init__(self, excel_file, root_dir, transform=None):
        self.data = pd.read_excel(excel_file)
        self.root_dir = root_dir
        self.transform = transform

        # Filter out valid paths and corresponding labels
        self.image_paths = []
        self.labels = []
        for idx, row in self.data.iterrows():
            img_path = os.path.join(self.root_dir, row['midas_path'])
            if os.path.exists(img_path):
                self.image_paths.append(img_path)
                self.labels.append(row['clinical_impression_1'])

        print(f"Total valid paths found: {len(self.image_paths)}")

        # Convert labels to numerical format
        self.categories = sorted(list(set(self.labels)))
        self.label_map = {label: idx for idx, label in enumerate(self.categories)}

    def __len__(self):
        return len(self.image_paths)

    def __getitem__(self, idx):
        img_path = self.image_paths[idx]
        image = Image.open(img_path).convert('RGB')
        label = self.labels[idx]

        if self.transform:
            image = self.transform(image)

        return image, self.label_map[label]

# Define the Primary Capsule Layer
class PrimaryCapsules(nn.Module):
    def __init__(self, in_channels, out_channels, num_capsules, capsule_dim, kernel_size, stride):
        super(PrimaryCapsules, self).__init__()
        self.capsules = nn.ModuleList(
            [nn.Conv2d(in_channels, out_channels, kernel_size=kernel_size, stride=stride) for _ in range(num_capsules)]
        )
        self.capsule_dim = capsule_dim

    def forward(self, x):
        u = [capsule(x) for capsule in self.capsules]
        u = torch.cat(u, dim=1)
        u = u.view(x.size(0), -1, self.capsule_dim)
        return self.squash(u)

    @staticmethod
    def squash(s, dim=-1):
        squared_norm = (s ** 2).sum(dim=dim, keepdim=True)
        scale = squared_norm / (1 + squared_norm)
        return scale * s / torch.sqrt(squared_norm + 1e-8)

# Define the Secondary Capsule Layer
class SecondaryCapsules(nn.Module):
    def __init__(self, num_routes, num_capsules, in_channels, out_channels):
        super(SecondaryCapsules, self).__init__()
        self.num_routes = num_routes
        self.num_capsules = num_capsules
        self.route_weights = nn.Parameter(torch.randn(num_routes, num_capsules, in_channels, out_channels))

    def forward(self, x):
        batch_size = x.size(0)
        x = x.unsqueeze(2).unsqueeze(3)
        u_hat = torch.matmul(x, self.route_weights)
        u_hat = u_hat.view(batch_size, self.num_routes, self.num_capsules, -1)
        u_hat = u_hat.permute(0, 2, 1, 3)

        b = torch.zeros(batch_size, self.num_capsules, self.num_routes, 1).to(x.device)
        for i in range(3):  # Routing iterations
            c = F.softmax(b, dim=2)
            s = (c * u_hat).sum(dim=2)
            v = self.squash(s)
            b = b + (u_hat * v.unsqueeze(2)).sum(dim=-1, keepdim=True)

        return v

    @staticmethod
    def squash(s, dim=-1):
        squared_norm = (s ** 2).sum(dim=dim, keepdim=True)
        scale = squared_norm / (1 + squared_norm)
        return scale * s / torch.sqrt(squared_norm + 1e-8)

# Define the Capsule Network
class CapsuleNetwork(nn.Module):
    def __init__(self, num_classes, in_channels=1):
        super(CapsuleNetwork, self).__init__()
        self.conv1 = nn.Conv2d(in_channels, 256, kernel_size=9, stride=1)
        self.primary_capsules = PrimaryCapsules(256, 32 * 8, 32, 8, kernel_size=9, stride=2)
        self.num_routes = 32 * 6 * 6
        self.secondary_capsules = SecondaryCapsules(num_routes=self.num_routes, num_capsules=num_classes, in_channels=8, out_channels=16)

    def forward(self, x):
        x = F.relu(self.conv1(x))
        x = self.primary_capsules(x)
        x = self.secondary_capsules(x)
        return x

# Set up training
def train_capsule_network():
    excel_file = '/root/stanfordData4321/stanfordData4321/dataRef/release_midas.xlsx'
    root_dir = '/path/to/images'  # Update this path to where your images are stored

    # Define your transformations
    transform = transforms.Compose([
        transforms.Resize((128, 128)),  # Resizing to match input size
        transforms.ToTensor(),
    ])

    # Create the dataset and dataloader
    dataset = ExcelImageDataset(excel_file=excel_file, root_dir=root_dir, transform=transform)
    dataloader = DataLoader(dataset, batch_size=32, shuffle=True, num_workers=4)

    num_classes = len(dataset.categories)
    model = CapsuleNetwork(num_classes=num_classes, in_channels=3).to('cuda')  # Assuming RGB images

    # Define loss and optimizer
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

    # Training loop
    num_epochs = 10
    for epoch in range(num_epochs):
        model.train()
        running_loss = 0.0
        for i, (inputs, labels) in enumerate(dataloader):
            inputs, labels = inputs.to('cuda'), labels.to('cuda')

            optimizer.zero_grad()

            outputs = model(inputs)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()

            running_loss += loss.item()
            if i % 10 == 9:  # Print every 10 batches
                print(f"[Epoch {epoch+1}, Batch {i+1}] loss: {running_loss / 10:.3f}")
                running_loss = 0.0

    print("Training complete")

if __name__ == "__main__":
    train_capsule_network()
