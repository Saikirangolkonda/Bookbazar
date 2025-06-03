document.addEventListener("DOMContentLoaded", function () {
  const cards = document.querySelectorAll(".book-card");
  const modal = document.getElementById("book-modal");
  const closeBtn = modal.querySelector(".close");

  const cover = document.getElementById("modal-cover");
  const title = document.getElementById("modal-title");
  const author = document.getElementById("modal-author");
  const genre = document.getElementById("modal-genre");
  const desc = document.getElementById("modal-description");
  const price = document.getElementById("modal-price");

  // Handle book card clicks for modal
  cards.forEach(card => {
    card.addEventListener("click", (e) => {
      // Don't open modal if add-to-cart button was clicked
      if (e.target.closest('.add-to-cart')) {
        return;
      }

      const id = parseInt(card.dataset.id);

      fetch(`/api/book/${id}`)
        .then(res => res.json())
        .then(book => {
          cover.src = book.cover_image;
          cover.alt = book.title;
          title.textContent = book.title;
          author.textContent = book.author;
          genre.textContent = book.genre || 'Unknown Genre';
          desc.textContent = book.description || 'No description available.';
          price.textContent = `$${book.price.toFixed(2)}`;

          modal.style.display = 'flex';
        })
        .catch(error => {
          console.error('Error fetching book details:', error);
        });
    });
  });

  // Handle add-to-cart button clicks
  document.querySelectorAll('.add-to-cart').forEach(button => {
    button.addEventListener('click', (e) => {
      e.stopPropagation(); // Prevent modal from opening
      
      const card = e.target.closest('.book-card');
      const bookId = parseInt(card.dataset.id);
      
      // Add visual feedback
      const originalHTML = button.innerHTML;
      button.innerHTML = '<svg viewBox="0 0 24 24" style="width: 20px; height: 20px; fill: #10b981;"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>';
      button.style.backgroundColor = '#10b981';
      
      fetch('/api/add-to-cart', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ book_id: bookId })
      })
      .then(response => response.json())
      .then(data => {
        if (data.success || data.message) {
          console.log('Book added to cart:', data.message);
          
          // Reset button after 1 second
          setTimeout(() => {
            button.innerHTML = originalHTML;
            button.style.backgroundColor = '#e0e7ff';
          }, 1000);
        } else {
          console.error('Error adding to cart:', data.error);
          // Reset button immediately on error
          button.innerHTML = originalHTML;
          button.style.backgroundColor = '#e0e7ff';
        }
      })
      .catch(error => {
        console.error('Error:', error);
        // Reset button immediately on error
        button.innerHTML = originalHTML;
        button.style.backgroundColor = '#e0e7ff';
      });
    });
  });

  // Close modal handlers
  closeBtn.addEventListener("click", () => {
    modal.style.display = 'none';
  });

  modal.addEventListener("click", e => {
    if (e.target === modal) {
      modal.style.display = 'none';
    }
  });
});