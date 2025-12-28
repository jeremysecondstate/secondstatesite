from django.shortcuts import render

def home(request):
    return render(request, "home.html")

def about(request):
    return render(request, "about.html")

def contact(request):
    return render(request, "contact.html")

def gallery(request):
    # leave blank for now (later: pull from DB)
    return render(request, "gallery.html")

def pieces_sold(request):
    # leave blank for now (later: pull from DB)
    return render(request, "pieces_sold.html")
