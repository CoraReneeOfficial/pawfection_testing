// Script for handling gallery image management in edit_store.html
document.addEventListener('DOMContentLoaded', function() {
    // Handle gallery image removal
    const galleryPreview = document.querySelector('.gallery-preview');
    if (galleryPreview) {
        galleryPreview.addEventListener('click', function(e) {
            if (e.target.classList.contains('remove-image')) {
                const filename = e.target.dataset.filename;
                const galleryItem = e.target.closest('.gallery-item');
                
                // Remove the hidden input for this image
                galleryItem.querySelector('input[type="hidden"]').remove();
                
                // Add a hidden input to track removed images
                const removedInput = document.createElement('input');
                removedInput.type = 'hidden';
                removedInput.name = 'removed_gallery_images';
                removedInput.value = filename;
                document.querySelector('form').appendChild(removedInput);
                
                // Visually remove the gallery item
                galleryItem.style.opacity = '0';
                setTimeout(() => {
                    galleryItem.remove();
                }, 300);
            }
        });
    }
    
    // Preview uploaded images before form submission
    const galleryInput = document.getElementById('gallery_images');
    if (galleryInput) {
        galleryInput.addEventListener('change', function() {
            // Create preview container if it doesn't exist
            let previewContainer = document.querySelector('.upload-preview');
            if (!previewContainer) {
                previewContainer = document.createElement('div');
                previewContainer.classList.add('gallery-preview', 'upload-preview');
                galleryInput.parentNode.appendChild(previewContainer);
            } else {
                // Clear existing previews
                previewContainer.innerHTML = '';
            }
            
            // Generate previews for each selected file
            for (const file of this.files) {
                if (file.type.startsWith('image/')) {
                    const reader = new FileReader();
                    reader.onload = function(e) {
                        const previewItem = document.createElement('div');
                        previewItem.classList.add('gallery-item');
                        
                        const img = document.createElement('img');
                        img.src = e.target.result;
                        img.alt = 'Preview';
                        
                        previewItem.appendChild(img);
                        previewContainer.appendChild(previewItem);
                    };
                    reader.readAsDataURL(file);
                }
            }
            
            if (this.files.length > 0) {
                const countText = document.createElement('p');
                countText.classList.add('upload-count');
                countText.textContent = `${this.files.length} image${this.files.length > 1 ? 's' : ''} selected`;
                previewContainer.parentNode.insertBefore(countText, previewContainer);
            }
        });
    }
});
