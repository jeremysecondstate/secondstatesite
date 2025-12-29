from django.db import models

class Artwork(models.Model):
    title = models.CharField(max_length=255)
    artist = models.CharField(max_length=255)
    year = models.CharField(max_length=10, blank=True, null=True)  # New field
    medium = models.CharField(max_length=255, blank=True, null=True)
    paper_type = models.CharField(max_length=255, blank=True, null=True)  # New field
    printer = models.CharField(max_length=255, blank=True, null=True)  # New field
    publisher = models.CharField(max_length=255, blank=True, null=True)  # New field
    edition_size = models.CharField(max_length=50, blank=True, null=True)  # New field
    dimensions_text = models.CharField(max_length=255, blank=True, null=True)
    sheet_size = models.CharField(max_length=255, blank=True, null=True)  # New field
    catalog_number = models.CharField(max_length=255, blank=True, null=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_available = models.BooleanField(default=True)

class ArtworkImage(models.Model):
    artwork = models.ForeignKey(Artwork, related_name='images', on_delete=models.CASCADE)
    image = models.ImageField(upload_to='artworks/')

    def __str__(self):
        return f"{self.artwork.title} - Image {self.id}"
